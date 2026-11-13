#!/usr/bin/env python3
"""Внесение медицинских документов в раздел «Здоровье» (health-labs, режим intake).

Модель хранения (решение владельца 2026-09-29) — ровно два места:

  * ПЕРВОИСТОЧНИК — ~/…/SynologyDrive-home/Медицинские анализы/ (PDF/JPG/HTML
    как выданы клиникой). Скрипт его ТОЛЬКО читает: ни переименований, ни
    удалений, ни записи рядом.
  * ДАННЫЕ СТРАНИЦЫ — ~/…/SynologyDrive-home/Claude-Memory/Health/:
      labs.json      — числа (биомаркеры). ГЛАВНЫЙ файл, пересборки из CSV
                       больше нет (build_health_json.py — архив). Пишет только
                       этот скрипт → единственный писатель → пишем через зеркало.
      studies.json   — исследования (заключения). ДВА писателя: этот скрипт
                       (через зеркало) и страница (свободный текст, через
                       write-API с base_hash). Решение владельца 2026-09-29:
                       риск принят ради правки текста на сайте, прикрыт
                       бэкапами. Страница после записи скрипта получит 409 и
                       не затрёт его; обратное (зеркало отстало от правки на
                       сайте) ловится только частично — поэтому перед записью
                       копия обоих файлов в .intake-backups/ (+ .versions/
                       сервера и история версий Synology Drive).
      studies/       — копии файлов исследований (копия из первоисточника).
      intake-log.json — какие файлы первоисточника уже разобраны (внесены или
                       сознательно пропущены). По нему `scan` ищет новое.

Связь исследование ↔ биомаркеры хранится ОДНОЙ стороной: точка labs.json
несёт series[i].study = id исследования (+ src = имя файла первоисточника).
Обратное направление страница вычисляет сама. У большинства точек ссылки нет
(обычные анализы крови) — это норма.

Команды:
  intake.py scan                         — новые файлы первоисточника (нет в логе)
  intake.py apply PLAN.json              — dry-run: проверки + отчёт, ничего не пишет
  intake.py apply PLAN.json --apply      — записать (файлы → labs → studies → лог)
  intake.py mark --status skipped --note "…" ФАЙЛ…   [--apply]
                                         — пометить файлы разобранными без внесения
  intake.py set-ref REFS.json [--apply]  — нормы из клинических рекомендаций с
                                           источником (ref_src); норму из документа
                                           не трогает никогда
  intake.py selftest

Формат PLAN.json — в references/intake.md (скилл). Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

# Общие правила labs.json — одна реализация со страницей «Здоровье» (сервер сайта импортирует тот же модуль).
from labs_rules import (  # noqa: F401  (часть имён используют selftest и тесты через intake.*)
    ID_RE, ISO_RE, STUDY_ID_RE, STUDY_KINDS, STUDY_TEXT_FIELDS, auto_status, is_manual, manual_points, nfc,
    plan_check, recompute_marker, sha256_file, slug, valid_ref)

HOME = Path.home()
HEALTH = HOME / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Health"
SRC_DIR = HOME / "Library/CloudStorage/SynologyDrive-home/Медицинские анализы"

LOG_SCHEMA = "health-intake-log@1"

# Подсказка для scan: похоже ли имя файла на исследование (иначе — анализ).
# Форматы, которые Claude не читает как картинку: фото iPhone (HEIC/HEIF) — сначала в JPEG.
UNREADABLE_RE = re.compile(r"\.(heic|heif)$", re.I)
STUDY_HINT_RE = re.compile(
    r"экг|узи|цдс|кт\b|кт |мрт|рентген|флюорог|энмг|нейромиограф|эндоскоп|"
    r"офтальмолог|эхокг|допплер|скопия|РГ ", re.I)


class PlanError(Exception):
    pass


# ─────────────────────────── ввод-вывод ───────────────────────────
def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def write_atomic(p: Path, text: str) -> None:
    """Запись через временный файл в той же папке + rename: оборванная запись
    не оставит полуфайл, который синк унесёт на NAS."""
    fd, tmp = tempfile.mkstemp(prefix="." + p.name + ".", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def dump_labs(doc) -> str:
    # indent=1 — как писал build_health_json.py: diff остаётся читаемым.
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def dump_studies(doc) -> str:
    # Как пишет страница (saveStudies): indent=2 + перевод строки.
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"



# ─────────────────────────── studies.json ───────────────────────────
def load_studies(health: Path):
    p = health / "studies.json"
    if not p.exists():
        return {"schema": "health-studies@1", "updated": None, "studies": []}, None
    raw = p.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def backup_before_write(health: Path, stamp: str):
    """Копия labs.json и studies.json до записи — в .intake-backups/<stamp>-*.
    Если запись со старого зеркала затрёт правку, сделанную на сайте, есть
    из чего восстановить."""
    d = health / ".intake-backups"
    d.mkdir(exist_ok=True)
    out = []
    for name in ("labs.json", "studies.json"):
        if (health / name).exists():
            shutil.copy2(health / name, d / f"{stamp}-{name}")
            out.append(f"{stamp}-{name}")
    return out


def load_labs(health: Path):
    """labs.json и его sha256 на момент чтения — для проверки перед записью."""
    p = health / "labs.json"
    raw = p.read_bytes()
    return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def save_labs(health: Path, labs, loaded_hash):
    """Файл изменился с момента чтения (синк привёз чужую версию, вторая сессия, запись с сайта) — не пишем."""
    p = health / "labs.json"
    now = sha256_file(p) if p.exists() else None
    if now != loaded_hash:
        raise SystemExit("✗ labs.json изменился после чтения (синк, другая сессия или сайт) — "
                         "ничего НЕ записано. Перезапустите команду.")
    write_atomic(p, dump_labs(labs))


def save_studies(health: Path, doc, loaded_hash):
    """Последняя страховка: файл изменился с момента чтения (синк привёз чужую
    версию, вторая сессия) — не пишем, а останавливаемся."""
    p = health / "studies.json"
    now = sha256_file(p) if p.exists() else None
    if now != loaded_hash:
        raise SystemExit("✗ studies.json изменился после чтения (синк или другая сессия) — "
                         "studies.json и labs.json НЕ записаны. Перезапустите apply.")
    write_atomic(p, dump_studies(doc))


# ─────────────────────────── лог разобранных файлов ───────────────────────────
def load_log(health: Path):
    p = health / "intake-log.json"
    if not p.exists():
        return {"schema": LOG_SCHEMA, "updated": None, "files": {}}
    doc = read_json(p)
    if doc.get("schema") != LOG_SCHEMA:
        raise SystemExit(f"✗ {p.name}: неизвестная схема {doc.get('schema')!r}")
    return doc


def source_files(src: Path):
    return sorted(nfc(f.name) for f in src.iterdir()
                  if f.is_file() and not f.name.startswith("."))


# ─────────────────────────── статус точки ───────────────────────────
def apply_ops(ops, labs, studies, log, today):
    """Мутирует labs/studies/log в памяти. -> сводка."""
    labs.setdefault("categories", []).extend(ops["new_categories"])
    labs.setdefault("biomarkers", []).extend(ops["new_markers"])
    by_id = {m["id"]: m for m in labs["biomarkers"]}
    touched = set(m["id"] for m in ops["new_markers"])
    added = linked = 0
    for op in ops["items"]:
        if op["study"]:
            studies.setdefault("studies", []).append(op["study"])
        if op.get("add_files"):
            x = next(x for x in studies["studies"] if x["id"] == op["study_ref"])
            for a in op["add_files"]:
                if not x.get("file"):
                    x["file"] = a
                else:
                    x.setdefault("more_files", []).append(a)
        if op["study_ref"]:
            x = next((x for x in studies["studies"] if x["id"] == op["study_ref"]), None)
            if x is not None:
                x["src"] = sorted(set(x.get("src") or []) | set(op["src"]))
        for p in op["points"]:
            m = by_id[p["marker"]]
            if p["mode"] == "link":
                pt = [s for s in m["series"] if s["date"] == p["date"]][0]
                pt["study"] = op["sid"]
                pt.setdefault("src", op["src"][0])
                linked += 1
            else:
                m["series"].append(p["point"])
                added += 1
            touched.add(m["id"])
        for s in op["src"]:
            log["files"][s] = {"status": "ingested", "date": today,
                               **({"study": op["sid"]} if op["sid"] else {}),
                               "points": sum(1 for p in op["points"])}
    for mid in touched:
        if by_id[mid]["series"]:
            recompute_marker(by_id[mid])
    # Пустой маркер (new_markers без точек) странице не нужен.
    labs["biomarkers"] = [m for m in labs["biomarkers"] if m["series"]]
    labs["biomarkers"].sort(key=lambda b: (b["category"], b["name"]))
    labs["updated"] = today
    studies["updated"] = today
    log["updated"] = today
    return {"added": added, "linked": linked, "markers": len(touched),
            "studies": sum(1 for op in ops["items"] if op["study"])}


# ─────────────────────────── нормы из рекомендаций ───────────────────────────
def refs_check(refs, labs):
    """refs: {marker_id: {"ref": …, "src": "источник"}} -> (errors, ops).

    Норма из клинических рекомендаций (не из документа) ставится на точки, у
    которых нормы нет или она уже была из рекомендаций (ref_src). Норму,
    напечатанную в документе (ref без ref_src), не трогаем никогда."""
    errors, ops = [], []
    by_id = {m["id"]: m for m in labs.get("biomarkers", [])}
    for mid, r in refs.items():
        m = by_id.get(mid)
        if not m:
            errors.append(f"{mid}: маркера нет в labs.json")
            continue
        ref, src = r.get("ref"), (r.get("src") or "").strip()
        if ref is None or not valid_ref(ref):
            errors.append(f"{mid}: ref — {{low,high}} | {{op,value}} | {{text}}: {ref!r}")
            continue
        if not src:
            errors.append(f"{mid}: src обязателен — откуда норма (рекомендация, год, пол/возраст)")
            continue
        idx = [i for i, p in enumerate(m["series"]) if not is_manual(p) and (p.get("ref") is None or p.get("ref_src"))]
        kept = len(m["series"]) - len(idx)
        ops.append((mid, ref, src, idx, kept))
    return errors, ops


def cmd_set_ref(args):
    refs = read_json(args.refs)
    labs, labs_hash = load_labs(args.health)
    errors, ops = refs_check(refs, labs)
    by_id = {m["id"]: m for m in labs["biomarkers"]}
    for mid, ref, src, idx, kept in ops:
        m = by_id[mid]
        stat = [auto_status(m["series"][i].get("value"), ref) for i in idx]
        print(f"  · {mid}: {len(idx)} точ." + (f" (норма из документа у {kept} — не трогаю)" if kept else "")
              + f" → статусы {', '.join(stat) or '—'} · {src}")
    if errors:
        print(f"\n✗ BLOCKING ({len(errors)}) — ничего не записано:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    if not args.apply:
        print("\nDRY-RUN: ничего не записано. Для записи — --apply.")
        return 0
    today = args.today or date.today().isoformat()
    stamp = today + "-" + _dt.datetime.now().strftime("%H%M%S")
    backups = backup_before_write(args.health, stamp)
    for mid, ref, src, idx, _ in ops:
        m = by_id[mid]
        for i in idx:
            p = m["series"][i]
            p["ref"], p["ref_src"] = ref, src
            p["status"] = auto_status(p.get("value"), ref) if isinstance(p.get("value"), (int, float)) else p.get("status", "na")
        recompute_marker(m)
    labs["updated"] = today
    save_labs(args.health, labs, labs_hash)
    print(f"\n✓ нормы: маркеров {len(ops)}; бэкап до записи: .intake-backups/" + ", ".join(backups))
    return 0


# ─────────────────────────── команды ───────────────────────────
def cmd_scan(args):
    log = load_log(args.health)
    files = source_files(args.src)
    new = [f for f in files if f not in log["files"]]
    print(f"Первоисточник: {args.src}")
    print(f"  файлов {len(files)} · разобрано {len(files) - len(new)} · новых {len(new)}")
    for f in new:
        tag = "исследование?" if STUDY_HINT_RE.search(f) else "анализ?"
        print(f"  · [{tag}] {f}")
    heic = [f for f in new if UNREADABLE_RE.search(f)]
    if heic:
        print(f"  ⚠ HEIC/HEIF не читается ({len(heic)}): попросить владельца сохранить как JPEG "
              f"или отсканировать в PDF (references/intake.md, «Фото бумажных документов»)")
    gone = [f for f in log["files"] if f not in files]
    for f in gone:
        print(f"  ⚠ в логе, но нет в первоисточнике (переименован?): {f}")
    return 0


def cmd_mark(args):
    if args.status != "skipped":
        raise SystemExit("mark ставит только status=skipped (внесение — через apply)")
    if not (args.note or "").strip():
        raise SystemExit("mark: --note обязателен — почему файл пропущен")
    log = load_log(args.health)
    files = source_files(args.src)
    args.files = [nfc(f) for f in args.files]
    bad = [f for f in args.files if f not in files]
    if bad:
        raise SystemExit("✗ нет в первоисточнике: " + "; ".join(bad))
    today = args.today or date.today().isoformat()
    again = [f for f in args.files if f in log["files"]]
    for f in args.files:
        log["files"][f] = {"status": "skipped", "date": today, "note": args.note.strip()}
    log["updated"] = today
    print(f"{'ЗАПИСЬ' if args.apply else 'DRY-RUN'}: пометить пропущенными {len(args.files)} файл(ов)"
          + (f", из них уже были в логе: {len(again)}" if again else ""))
    if args.apply:
        write_atomic(args.health / "intake-log.json", json.dumps(log, ensure_ascii=False, indent=2) + "\n")
        print("✓ intake-log.json")
    return 0


def cmd_apply(args):
    plan = read_json(args.plan)
    labs, labs_hash = load_labs(args.health)
    log = load_log(args.health)
    studies, studies_hash = load_studies(args.health)
    errors, warnings, ops = plan_check(plan, labs, studies, log, args.src, args.health / "studies",
                                       allow_repeat=args.allow_repeat)
    print(f"План: {args.plan.name} · пунктов {len(ops['items'])} · "
          f"новых категорий {len(ops['new_categories'])} · новых маркеров {len(ops['new_markers'])}")
    for op in ops["items"]:
        st = op["study"]
        head = (f"исследование {st['id']} ({st['kind']} · {st['area']})" if st
                else f"к исследованию {op['study_ref']}" if op["study_ref"] else "без исследования")
        n_add = sum(1 for p in op["points"] if p["mode"] == "add")
        n_link = sum(1 for p in op["points"] if p["mode"] == "link")
        print(f"  · {', '.join(op['src'])} → {head}; точек +{n_add}, привязок {n_link}"
              + (f"; файлы: {', '.join(a for _, a in op['copies'])}" if op["copies"] else ""))
    for w in warnings:
        print(f"  ⚠ {w}")
    if errors:
        print(f"\n✗ BLOCKING ({len(errors)}) — ничего не записано:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    if not args.apply:
        print("\nDRY-RUN: проверки пройдены, ничего не записано. Для записи — --apply.")
        return 0
    today = args.today or date.today().isoformat()
    manual_before = manual_points(labs)
    summary = apply_ops(ops, labs, studies, log, today)
    if manual_points(labs) != manual_before:     # страховка: ручные точки владельца не меняются ни при каких правках плана
        print("✗ внутренняя ошибка: план затронул точки source=manual — ничего не записано.")
        return 1
    # Порядок: файлы → studies → labs → лог. studies первым: только его запись
    # может отказать (файл изменился после чтения) — тогда labs ещё не тронут и
    # точки не ссылаются на несуществующее исследование. Лог последним:
    # упавший прогон не пометит файлы разобранными.
    stamp = today + "-" + _dt.datetime.now().strftime("%H%M%S")
    backups = backup_before_write(args.health, stamp)
    sd = args.health / "studies"
    sd.mkdir(exist_ok=True)
    for op in ops["items"]:
        for fr, a in op["copies"]:
            if not (sd / a).exists():
                shutil.copy2(args.src / fr, sd / a)
    touched_studies = any(op["study"] or op["study_ref"] for op in ops["items"])
    if touched_studies:
        save_studies(args.health, studies, studies_hash)
    save_labs(args.health, labs, labs_hash)
    write_atomic(args.health / "intake-log.json", json.dumps(log, ensure_ascii=False, indent=2) + "\n")
    print(f"\n✓ записано: точек +{summary['added']}, привязок {summary['linked']}, "
          f"маркеров затронуто {summary['markers']}, исследований +{summary['studies']}")
    print("  labs.json" + (", studies.json" if touched_studies else "") + ", intake-log.json — через зеркало Synology")
    print("  бэкап до записи: .intake-backups/" + ", ".join(backups))
    return 0


# ─────────────────────────── selftest ───────────────────────────
def selftest() -> int:
    ok = fail = 0

    def check(what, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
        else:
            fail += 1
            print(f"  ✗ {what}: получено {got!r}, ожидалось {want!r}")

    check("статус норма", auto_status(5, {"low": 1, "high": 10}), "norm")
    check("статус выше", auto_status(11, {"low": 1, "high": 10}), "high")
    check("статус ниже", auto_status(0.5, {"low": 1, "high": 10}), "low")
    check("статус < порог", auto_status(21, {"op": "<", "value": 21}), "high")
    check("статус ≥ порог", auto_status(0.8, {"op": "≥", "value": 1}), "low")
    check("статус без ref", auto_status(5, None), "na")
    check("статус текст", auto_status(None, {"low": 1, "high": 2}), "na")
    check("ref интервал", valid_ref({"low": 1, "high": 2}), True)
    check("ref перевёрнут", valid_ref({"low": 3, "high": 2}), False)
    check("ref op", valid_ref({"op": "≥", "value": 1}), True)
    check("ref мусор", valid_ref({"low": 1}), False)
    check("slug", slug("ЭКГ-сердце"), "ekg-serdce")
    check("подсказка ЭКГ", bool(STUDY_HINT_RE.search("2025-10-16 ЭКГ.pdf")), True)
    check("подсказка анализ", bool(STUDY_HINT_RE.search("2023-03-14 Общий белок.pdf")), False)
    check("HEIC не читается", bool(UNREADABLE_RE.search("IMG_0412.HEIC")), True)
    check("JPG читается", bool(UNREADABLE_RE.search("2019-05-12 Анализ.jpg")), False)
    check("NFD → NFC", nfc(unicodedata.normalize("NFD", "Электронейромиография")), "Электронейромиография")
    print(f"{'✓ selftest OK' if not fail else '✗ ЕСТЬ ПАДЕНИЯ'}: {ok} проверок, {fail} падений")
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Внесение медицинских документов в «Здоровье»")
    ap.add_argument("--health", type=Path, default=HEALTH)
    ap.add_argument("--src", type=Path, default=SRC_DIR)
    ap.add_argument("--today")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    a = sub.add_parser("apply")
    a.add_argument("plan", type=Path)
    a.add_argument("--apply", action="store_true")
    a.add_argument("--allow-repeat", action="store_true")
    m = sub.add_parser("mark")
    m.add_argument("files", nargs="+")
    m.add_argument("--status", default="skipped")
    m.add_argument("--note")
    m.add_argument("--apply", action="store_true")
    r = sub.add_parser("set-ref", help="нормы из клинических рекомендаций (с источником)")
    r.add_argument("refs", type=Path)
    r.add_argument("--apply", action="store_true")
    sub.add_parser("selftest")
    args = ap.parse_args()
    if args.cmd == "selftest":
        return selftest()
    return {"scan": cmd_scan, "apply": cmd_apply, "mark": cmd_mark, "set-ref": cmd_set_ref}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

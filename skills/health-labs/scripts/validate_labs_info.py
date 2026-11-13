#!/usr/bin/env python3
"""
validate_labs_info.py

Детерминированный coverage/валидатор/merge-движок справочника биомаркеров
для скилла health-labs.

Контракт `health-biomarkers-info@1` — плоский словарь `info: {id: {what, up,
down}}`. В отличие от `health-meds`, здесь нет полей человека и нет
per-entry провенанса (`sources`/`confidence`) — решение владельца 2026-08-05:
справочник биомаркеров — общая физиология, а не препарат-специфичные факты,
поэтому единственный провенанс — общая дата `generated` на файле. Единственная
пометка человека — `manual: true` на записи, внесённой со страницы: merge её не
переписывает (skip_manual).

CLI:
    python3 validate_labs_info.py coverage --labs labs.json --info biomarkers-info.json [--json]
    python3 validate_labs_info.py validate --info biomarkers-info.json [--labs labs.json] [--json]
    python3 validate_labs_info.py merge --info biomarkers-info.json --enrich enrich.json \
            [--labs labs.json] [--apply] [--overwrite]

merge по умолчанию — dry-run: печатает отчёт и не трогает файл. Без --overwrite
уже существующая запись не переписывается — только добавляются новые id.
Запись (--apply) происходит ТОЛЬКО при отсутствии blocking-issue у результата.

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from typing import Any

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

SCHEMA = "health-biomarkers-info@1"

# Дефолтная категория categorize() в build_health_json.py, когда ни одно
# правило CATEGORY_RULES не подошло. Совпадение — сигнал недостающего
# правила, а не то, что маркер и правда биохимия крови (см. coverage()).
DEFAULT_CATEGORY = "biochem"


def _issue(severity: str, category: str, message: str, marker_id: str | None = None) -> dict:
    out = {"severity": severity, "category": category, "message": message}
    if marker_id is not None:
        out["id"] = marker_id
    return out


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def load_labs_markers(labs: dict) -> dict[str, str]:
    """id биомаркера -> category, из labs.json."""
    out: dict[str, str] = {}
    for b in labs.get("biomarkers", []):
        if isinstance(b, dict) and isinstance(b.get("id"), str):
            cat = b.get("category")
            out[b["id"]] = cat if isinstance(cat, str) else ""
    return out


# ─────────────────────────── coverage ───────────────────────────

def compute_coverage(labs_markers: dict[str, str], info: dict) -> dict:
    """missing — id без записи; default_category_flag — подмножество missing
    с дефолтной категорией (сигнал недостающего CATEGORY_RULE); orphans — id
    в справочнике, которых больше нет в labs.json."""
    info_ids = set(info.keys()) if isinstance(info, dict) else set()
    labs_ids = set(labs_markers)
    missing = sorted(labs_ids - info_ids)
    default_category_flag = sorted(mid for mid in missing if labs_markers[mid] == DEFAULT_CATEGORY)
    orphans = sorted(info_ids - labs_ids)
    return {
        "missing": [{"id": mid, "category": labs_markers[mid]} for mid in missing],
        "default_category_flag": default_category_flag,
        "orphans": orphans,
    }


# ─────────────────────────── валидация ───────────────────────────

def _validate_entry_fields(entry: dict, where: str) -> list[dict]:
    issues: list[dict] = []
    what = entry.get("what")
    if not isinstance(what, list) or not what or not all(
        isinstance(w, str) and w.strip() for w in what
    ):
        issues.append(_issue("blocking", "what", "what — непустой список непустых строк", where))
    for field in ("up", "down"):
        v = entry.get(field)
        if not isinstance(v, str) or not v.strip():
            issues.append(_issue("blocking", field, f"{field} — непустая строка", where))
    return issues


def validate_info(doc: Any, labs_ids: set[str] | None = None) -> list[dict]:
    """Проверяет biomarkers-info.json. → плоский список issues."""
    if not isinstance(doc, dict):
        return [_issue("blocking", "root", "корень biomarkers-info.json должен быть объектом")]

    issues: list[dict] = []
    if doc.get("schema") != SCHEMA:
        issues.append(_issue("blocking", "schema",
                             f"schema должна быть {SCHEMA!r}, получено {doc.get('schema')!r}"))
    if "generated" in doc and not _is_iso_date(doc.get("generated")):
        issues.append(_issue("warning", "generated",
                             f"generated не ISO-дата: {doc.get('generated')!r}"))

    info = doc.get("info")
    if not isinstance(info, dict):
        issues.append(_issue("blocking", "info", "info должен быть объектом {id: {what,up,down}}"))
        return issues

    for mid, entry in info.items():
        where = mid if isinstance(mid, str) and mid else "?"
        if not isinstance(entry, dict):
            issues.append(_issue("blocking", "entry", "запись должна быть объектом", where))
            continue
        issues.extend(_validate_entry_fields(entry, where))
        if labs_ids is not None and mid not in labs_ids:
            issues.append(_issue("warning", "orphan",
                                 f"{mid!r} есть в справочнике, но такого id больше нет в labs.json",
                                 where))
    return issues


# ─────────────────────────── merge ───────────────────────────

def merge_info(doc: dict, enrich: dict, *, today: str, overwrite: bool = False,
               labs_ids: set[str] | None = None, manual: bool = False) -> tuple[dict, list[dict]]:
    """Вливает новые записи в biomarkers-info.json. Возвращает (новый_doc, отчёт).

    enrich: {marker_id: {"what": [...], "up": "...", "down": "..."}}

    Без overwrite уже существующая запись не трогается — merge только
    добавляет id, которых ещё нет (защита от случайной перезаписи прошлой
    работы). labs_ids, если передан, отсекает id, которых нет в labs.json —
    типовая опечатка, а не факт о биомаркере.

    manual=True — правка человека со страницы: запись получает `manual: true`
    и заменяет любую прежнюю. Запись с `manual: true` скилл не переписывает
    даже с overwrite (action skip_manual): ручной текст не затирается.
    """
    out = json.loads(json.dumps(doc))  # глубокая копия: вход не мутируем
    if not isinstance(out.get("info"), dict):
        out["info"] = {}

    report: list[dict] = []
    for mid, payload in enrich.items():
        if labs_ids is not None and mid not in labs_ids:
            report.append({"id": mid, "action": "reject_unknown_id",
                           "reason": "такого id нет в labs.json"})
            continue

        entry_issues = _validate_entry_fields(payload if isinstance(payload, dict) else {}, mid)
        if entry_issues:
            report.append({"id": mid, "action": "reject_invalid",
                           "reason": "; ".join(i["message"] for i in entry_issues)})
            continue

        existing = mid in out["info"]
        if existing and not manual and isinstance(out["info"][mid], dict) and out["info"][mid].get("manual") is True:
            report.append({"id": mid, "action": "skip_manual"})
            continue
        if existing and not overwrite and not manual:
            report.append({"id": mid, "action": "skip_existing"})
            continue

        out["info"][mid] = {
            "what": list(payload["what"]),
            "up": payload["up"],
            "down": payload["down"],
        }
        if manual:
            out["info"][mid]["manual"] = True
        report.append({"id": mid, "action": "overwrite" if existing else "add"})

    if any(r["action"] in ("add", "overwrite") for r in report):
        out["generated"] = today
    return out, report


# ─────────────────────────── CLI ───────────────────────────

def _read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: str, doc: Any) -> None:
    """Атомарная запись: мастер-файл на Mac, полуфайла быть не должно."""
    body = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".labs-info-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _print_issues(issues: list[dict]) -> None:
    if not issues:
        print("  issues: нет")
        return
    for sev in ("blocking", "warning", "info"):
        for i in [x for x in issues if x["severity"] == sev]:
            tag = i.get("id", "—")
            print(f"  [{sev}] {tag}: {i['message']}")


def _print_coverage(cov: dict) -> None:
    print(f"  без справки: {len(cov['missing'])}")
    for m in cov["missing"]:
        flag = "  ⚠ дефолтная категория — проверить CATEGORY_RULES" if m["id"] in cov["default_category_flag"] else ""
        print(f"    {m['id']} ({m['category'] or '—'}){flag}")
    if cov["orphans"]:
        print(f"  orphans (есть в справочнике, нет в labs.json): {len(cov['orphans'])}")
        for o in cov["orphans"]:
            print(f"    {o}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Coverage/валидатор/merge справочника биомаркеров health-biomarkers-info@1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("coverage", help="маркеры без справки + orphans")
    c.add_argument("--labs", required=True)
    c.add_argument("--info", required=True)
    c.add_argument("--json", action="store_true", help="машиночитаемо")

    v = sub.add_parser("validate", help="проверить biomarkers-info.json")
    v.add_argument("--info", required=True)
    v.add_argument("--labs", help="labs.json — включает проверку orphan id")
    v.add_argument("--json", action="store_true", help="issues машиночитаемо")

    m = sub.add_parser("merge", help="влить справку (по умолчанию dry-run)")
    m.add_argument("--info", required=True)
    m.add_argument("--enrich", required=True)
    m.add_argument("--labs", help="labs.json — проверка, что id существует")
    m.add_argument("--today", default=date.today().isoformat())
    m.add_argument("--apply", action="store_true", help="записать файл")
    m.add_argument("--overwrite", action="store_true",
                   help="переписывать уже существующие записи (по умолчанию — нет)")

    args = ap.parse_args(argv)

    if args.cmd == "coverage":
        labs_markers = load_labs_markers(_read_json(args.labs))
        info = _read_json(args.info).get("info", {})
        cov = compute_coverage(labs_markers, info if isinstance(info, dict) else {})
        if args.json:
            print(json.dumps(cov, ensure_ascii=False, indent=2))
        else:
            print(f"Coverage {args.info} vs {args.labs}")
            _print_coverage(cov)
        return 0

    labs_ids = set(load_labs_markers(_read_json(args.labs))) if getattr(args, "labs", None) else None

    if args.cmd == "validate":
        doc = _read_json(args.info)
        issues = validate_info(doc, labs_ids)
        if args.json:
            print(json.dumps(issues, ensure_ascii=False, indent=2))
        else:
            print(f"Проверка {args.info}")
            _print_issues(issues)
        return 1 if any(i["severity"] == "blocking" for i in issues) else 0

    doc = _read_json(args.info)
    new_doc, report = merge_info(doc, _read_json(args.enrich), today=args.today,
                                 overwrite=args.overwrite, labs_ids=labs_ids)
    issues = validate_info(new_doc, labs_ids)
    blocking = [i for i in issues if i["severity"] == "blocking"]

    print(f"Merge {args.info} ({'запись' if args.apply else 'dry-run'})")
    for r in report:
        bits = {
            "add": "добавлено",
            "overwrite": "перезаписано (--overwrite)",
            "skip_existing": "не тронуто (уже есть — используйте --overwrite для замены)",
            "skip_manual": "не тронуто (текст внесён вручную со страницы)",
            "reject_invalid": f"ОТКЛОНЕНО (невалидные данные): {r.get('reason', '')}",
            "reject_unknown_id": f"ОТКЛОНЕНО: {r.get('reason', '')}",
        }[r["action"]]
        print(f"  {r['id']}: {bits}")
    _print_issues(issues)

    if blocking:
        print(f"\n✗ {len(blocking)} blocking-issue — файл НЕ записан.")
        return 1
    if args.apply:
        hub_settings.require_ai(args.info, "validate_labs_info.py merge --apply", "запись справочника биомаркеров", zones=("Health",))   # вход — вывод модели
        _write_json_atomic(args.info, new_doc)
        print(f"\n✓ Записано: {args.info}")
    else:
        print("\n✓ Валидация зелёная. Запись: повторить с --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())

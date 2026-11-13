#!/usr/bin/env python3
"""
Регрессионные тесты для validate_labs_info.py (health-labs).

Запуск из корня репозитория:
    python3 skills/health-labs/tests/test_validate_labs_info.py

Медданных здесь нет и быть не может — только синтетические фикстуры:
репозиторий уезжает на GitHub.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "health-labs" / "scripts" / "validate_labs_info.py"

sys.path.insert(0, str(SCRIPT.parent))
from validate_labs_info import (  # noqa: E402
    DEFAULT_CATEGORY,
    compute_coverage,
    load_labs_markers,
    merge_info,
    validate_info,
)

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def sev(issues, severity, category=None):
    return [i for i in issues
            if i["severity"] == severity and (category is None or i["category"] == category)]


def has(issues, severity, category):
    return bool(sev(issues, severity, category))


TODAY = "2026-08-05"


def entry(**over):
    base = {"what": ["Что измеряет тест.", "Оговорка интерпретации."],
            "up": "Причины повышения.", "down": "Причины понижения."}
    base.update(over)
    return base


def info_doc(**entries):
    return {"schema": "health-biomarkers-info@1", "generated": TODAY,
            "info": entries or {"glucose": entry()}}


def labs_doc(*markers):
    markers = markers or [{"id": "glucose", "category": "biochem"}]
    return {"schema": "health-labs@1", "biomarkers": [
        {"id": m["id"], "name": m["id"], "category": m.get("category", "biochem"),
         "kind": "num", "unit": "", "ref": None, "series": []} for m in markers
    ]}


# ─────────────────── схема и обязательные поля ───────────────────

def test_schema():
    print("\nСхема и обязательные поля")
    check("валидный документ — без issues", validate_info(info_doc()) == [])
    check("пустой info валиден", validate_info({"schema": "health-biomarkers-info@1", "info": {}}) == [])
    check("чужая schema → blocking",
          has(validate_info({"schema": "health-biomarkers-info@2", "info": {}}), "blocking", "schema"))
    check("корень не объект → blocking", has(validate_info([]), "blocking", "root"))
    check("info не объект → blocking",
          has(validate_info({"schema": "health-biomarkers-info@1", "info": []}), "blocking", "info"))
    check("generated не ISO → warning",
          has(validate_info({"schema": "health-biomarkers-info@1", "generated": "05.08.2026", "info": {}}),
              "warning", "generated"))
    check("запись не объект → blocking",
          has(validate_info({"schema": "health-biomarkers-info@1", "info": {"glucose": "текст"}}),
              "blocking", "entry"))


def test_entry_fields():
    print("\nПоля записи (what/up/down)")
    check("пустой what → blocking", has(validate_info(info_doc(glucose=entry(what=[]))), "blocking", "what"))
    check("what не список → blocking",
          has(validate_info(info_doc(glucose=entry(what="строка"))), "blocking", "what"))
    check("what со строкой-пустышкой → blocking",
          has(validate_info(info_doc(glucose=entry(what=["ок", "  "]))), "blocking", "what"))
    check("пустой up → blocking", has(validate_info(info_doc(glucose=entry(up=""))), "blocking", "up"))
    check("пустой down → blocking", has(validate_info(info_doc(glucose=entry(down="  "))), "blocking", "down"))
    check("up не строка → blocking", has(validate_info(info_doc(glucose=entry(up=None))), "blocking", "up"))


def test_orphans():
    print("\nOrphan id (есть в справочнике, нет в labs.json)")
    doc = info_doc(glucose=entry(), ghost=entry())
    issues = validate_info(doc, labs_ids={"glucose"})
    check("orphan → warning, не blocking", has(issues, "warning", "orphan") and not has(issues, "blocking", "orphan"))
    check("живой id не помечен orphan",
          not any(i.get("id") == "glucose" and i["category"] == "orphan" for i in issues))
    check("без --labs orphan не проверяется", validate_info(doc) == [])


# ─────────────────── coverage ───────────────────

def test_coverage():
    print("\ncoverage")
    labs_markers = load_labs_markers(labs_doc(
        {"id": "glucose", "category": "biochem"},
        {"id": "ldl", "category": "lipid"},
        {"id": "mystery_marker", "category": "biochem"},
    ))
    check("load_labs_markers — category сохранена", labs_markers["ldl"] == "lipid")

    cov = compute_coverage(labs_markers, {"glucose": entry()})
    missing_ids = {m["id"] for m in cov["missing"]}
    check("missing — только id без записи", missing_ids == {"ldl", "mystery_marker"})
    check("default_category_flag — подмножество missing с дефолтной категорией",
          cov["default_category_flag"] == ["mystery_marker"])
    check("покрытый id не в default_category_flag", "glucose" not in cov["default_category_flag"])

    cov_orphan = compute_coverage(labs_markers, {"glucose": entry(), "ghost": entry()})
    check("orphans — id справочника без пары в labs.json", cov_orphan["orphans"] == ["ghost"])
    check("DEFAULT_CATEGORY соответствует biochem-фолбэку build_health_json.py",
          DEFAULT_CATEGORY == "biochem")


# ─────────────────── merge ───────────────────

def test_merge_basic():
    print("\nmerge — добавление новых записей")
    doc = info_doc()  # только glucose
    new_doc, report = merge_info(doc, {"ldl": entry()}, today=TODAY)
    check("новая запись добавлена", new_doc["info"]["ldl"]["up"] == "Причины повышения.")
    check("action=add", report[0]["action"] == "add")
    check("generated обновлён при записи", new_doc["generated"] == TODAY)
    check("вход не мутирован", "ldl" not in doc["info"])


def test_merge_overwrite_guard():
    print("\nmerge — защита существующей записи без --overwrite")
    OLD_DATE = "2026-07-17"
    doc = info_doc(glucose=entry(up="старый текст"))
    doc["generated"] = OLD_DATE
    new_doc, report = merge_info(doc, {"glucose": entry(up="новый текст")}, today=TODAY)
    check("существующая запись НЕ тронута без --overwrite", new_doc["info"]["glucose"]["up"] == "старый текст")
    check("action=skip_existing", report[0]["action"] == "skip_existing")
    check("generated не обновлён, если ничего не записано", new_doc["generated"] == OLD_DATE)

    new_doc2, report2 = merge_info(doc, {"glucose": entry(up="новый текст")}, today=TODAY, overwrite=True)
    check("с --overwrite запись переписана", new_doc2["info"]["glucose"]["up"] == "новый текст")
    check("action=overwrite", report2[0]["action"] == "overwrite")
    check("с --overwrite generated обновлён", new_doc2["generated"] == TODAY)


def test_merge_manual():
    print("\nmerge — ручная правка со страницы (manual) и запись скилла")
    doc = info_doc(glucose=entry(up="текст скилла"))
    new_doc, report = merge_info(doc, {"glucose": entry(up="текст человека")}, today=TODAY, overwrite=True, manual=True)
    check("ручная правка заменяет запись скилла", new_doc["info"]["glucose"]["up"] == "текст человека")
    check("запись помечена manual: true", new_doc["info"]["glucose"].get("manual") is True)
    check("action=overwrite", report[0]["action"] == "overwrite")
    _, rep_new = merge_info(info_doc(), {"ldl": entry()}, today=TODAY, manual=True)
    check("ручная запись нового id — add", rep_new[0]["action"] == "add")
    for ow in (False, True):
        d2, r2 = merge_info(new_doc, {"glucose": entry(up="снова скилл")}, today=TODAY, overwrite=ow)
        check(f"скилл не затирает ручную запись (overwrite={ow})", d2["info"]["glucose"]["up"] == "текст человека" and r2[0]["action"] == "skip_manual")
    check("ручная запись проходит validate_info", not [i for i in validate_info(new_doc) if i["severity"] == "blocking"])
    d3, _ = merge_info(doc, {"ldl": entry()}, today=TODAY, overwrite=True)
    check("запись скилла без manual остаётся перезаписываемой", d3["info"]["glucose"].get("manual") is None)


def test_merge_unknown_id():
    print("\nmerge — id, которого нет в labs.json")
    doc = info_doc()
    new_doc, report = merge_info(doc, {"typo_id": entry()}, today=TODAY, labs_ids={"glucose"})
    check("неизвестный id отклонён", "typo_id" not in new_doc["info"])
    check("action=reject_unknown_id", report[0]["action"] == "reject_unknown_id")

    new_doc2, report2 = merge_info(doc, {"typo_id": entry()}, today=TODAY, labs_ids=None)
    check("без --labs проверка id пропускается — запись добавлена", "typo_id" in new_doc2["info"])


def test_merge_invalid_payload():
    print("\nmerge — невалидный enrich-payload не пишется")
    OLD_DATE = "2026-07-17"
    doc = info_doc()
    doc["generated"] = OLD_DATE
    new_doc, report = merge_info(doc, {"ldl": entry(what=[])}, today=TODAY)
    check("пустой what → не записано", "ldl" not in new_doc["info"])
    check("action=reject_invalid", report[0]["action"] == "reject_invalid")
    check("generated не тронут, если ничего не записано", new_doc["generated"] == OLD_DATE)


# ─────────────────── CLI (subprocess, атомарная запись) ───────────────────

def test_cli():
    print("\nCLI")
    with tempfile.TemporaryDirectory() as td:
        info_p = Path(td) / "biomarkers-info.json"
        labs_p = Path(td) / "labs.json"
        enr_p = Path(td) / "enrich.json"

        info_p.write_text(json.dumps(info_doc()), encoding="utf-8")
        labs_p.write_text(json.dumps(labs_doc(
            {"id": "glucose", "category": "biochem"}, {"id": "ldl", "category": "lipid"})),
            encoding="utf-8")

        # coverage
        r = subprocess.run([sys.executable, str(SCRIPT), "coverage",
                            "--labs", str(labs_p), "--info", str(info_p), "--json"],
                           capture_output=True, text=True)
        check("coverage exit 0", r.returncode == 0)
        cov = json.loads(r.stdout)
        check("coverage находит ldl", {m["id"] for m in cov["missing"]} == {"ldl"})

        # merge dry-run
        enr_p.write_text(json.dumps({"ldl": entry()}), encoding="utf-8")
        before = info_p.read_text(encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--info", str(info_p),
                            "--enrich", str(enr_p), "--labs", str(labs_p), "--today", TODAY],
                           capture_output=True, text=True)
        check("merge dry-run exit 0", r.returncode == 0)
        check("merge dry-run НЕ пишет файл", info_p.read_text(encoding="utf-8") == before)
        check("dry-run сообщает про --apply", "--apply" in r.stdout)

        # merge --apply
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--info", str(info_p),
                            "--enrich", str(enr_p), "--labs", str(labs_p), "--today", TODAY,
                            "--apply"], capture_output=True, text=True)
        check("merge --apply exit 0", r.returncode == 0)
        written = json.loads(info_p.read_text(encoding="utf-8"))
        check("merge --apply записывает ldl", "ldl" in written["info"])
        check("merge --apply обновляет generated", written["generated"] == TODAY)

        # validate после записи — покрытие полное, issues нет
        r = subprocess.run([sys.executable, str(SCRIPT), "validate", "--info", str(info_p),
                            "--labs", str(labs_p)], capture_output=True, text=True)
        check("validate после merge — exit 0", r.returncode == 0)

        # glucose уже существует (без --overwrite) — CLI прогоняет skip_existing,
        # exit 0, файл не меняется (не blocking-случай).
        enr_p.write_text(json.dumps({"glucose": {"what": [], "up": "", "down": ""}}), encoding="utf-8")
        before2 = info_p.read_text(encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--info", str(info_p),
                            "--enrich", str(enr_p), "--today", TODAY, "--apply"],
                           capture_output=True, text=True)
        check("merge: glucose уже есть без --overwrite → skip, exit 0", r.returncode == 0)
        check("файл не изменился (skip_existing)", info_p.read_text(encoding="utf-8") == before2)

        # теперь настоящий blocking-случай: новый id с невалидным содержимым.
        enr_p.write_text(json.dumps({"nonexistent_but_valid_shape": {"what": [], "up": "", "down": ""}}),
                         encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), "merge", "--info", str(info_p),
                            "--enrich", str(enr_p), "--today", TODAY, "--apply"],
                           capture_output=True, text=True)
        check("merge: невалидный payload — не blocking (reject_invalid), файл не тронут",
              r.returncode == 0 and info_p.read_text(encoding="utf-8") == before2)


def main() -> int:
    print("=" * 60)
    print("validate_labs_info.py — регрессионные тесты")
    print("=" * 60)
    test_schema()
    test_entry_fields()
    test_orphans()
    test_coverage()
    test_merge_basic()
    test_merge_overwrite_guard()
    test_merge_manual()
    test_merge_unknown_id()
    test_merge_invalid_payload()
    test_cli()
    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Тесты labs_rules.py (общие правила labs.json: скилл health-labs и сервер сайта).

Запуск из корня репозитория:
    python3 skills/health-labs/tests/test_labs_rules.py

Только синтетика. Контракт: одна реализация auto_status / valid_ref / recompute_marker / plan_check
(intake.py импортирует их отсюда) и check_manual_edit — что странице разрешено менять в labs.json.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import intake  # noqa: E402
import labs_rules as lr  # noqa: E402

run = fail = 0


def check(name, cond, detail=""):
    global run, fail
    run += 1
    if not cond:
        fail += 1
    print(f"  [{'OK' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


SK = {"date": "2026-01-10", "value": 5.0, "text": None, "unit": "ед", "ref": {"low": 1, "high": 10},
      "status": "norm", "lab": "Лаб", "study": None, "src": "doc.pdf"}
OLD = {"schema": "health-labs@1", "generated": "2026-01-01", "person": {"sex": "x"},
       "categories": [{"key": "c1", "name": "Кат"}],
       "biomarkers": [{"id": "aa", "name": "Показатель", "category": "c1", "kind": "num", "unit": "ед",
                       "ref": {"low": 1, "high": 10}, "series": [dict(SK)]}], "updated": "2026-01-10"}


def man(date, value, **kw):
    return {"date": date, "value": value, "text": None, "unit": "ед", "ref": {"low": 1, "high": 10},
            "status": "norm", "lab": None, "source": "manual", **kw}


def edit(mut):
    new = copy.deepcopy(OLD)
    mut(new)
    return lr.check_manual_edit(copy.deepcopy(OLD), new)


def main():
    print("одна реализация со скиллом")
    check("intake.auto_status is labs_rules.auto_status", intake.auto_status is lr.auto_status)
    check("intake.valid_ref / recompute_marker / plan_check — те же функции",
          intake.valid_ref is lr.valid_ref and intake.recompute_marker is lr.recompute_marker
          and intake.plan_check is lr.plan_check)
    check("модуль без побочных эффектов: нет путей к данным", not hasattr(lr, "HEALTH") and not hasattr(lr, "SRC_DIR"))

    print("auto_status / valid_ref")
    check("норма", lr.auto_status(5, {"low": 1, "high": 10}) == "norm")
    check("выше", lr.auto_status(11, {"low": 1, "high": 10}) == "high")
    check("ниже", lr.auto_status(0.5, {"low": 1, "high": 10}) == "low")
    check("порог <", lr.auto_status(21, {"op": "<", "value": 21}) == "high")
    check("текст/нет референса → na", lr.auto_status(None, {"low": 1, "high": 2}) == "na" and lr.auto_status(5, None) == "na")
    check("ref: интервал/порог/текст/null", lr.valid_ref({"low": 1, "high": 2}) and lr.valid_ref({"op": "≥", "value": 1})
          and lr.valid_ref({"text": "до 5"}) and lr.valid_ref(None))
    check("ref: перевёрнутый и мусор", not lr.valid_ref({"low": 3, "high": 2}) and not lr.valid_ref({"low": 1}))

    print("check_manual_edit: разрешённое")
    errs, new = edit(lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 12, status="norm")))
    check("ручная точка добавляется, статус считает модуль (12 > 10 → high)",
          not errs and new["biomarkers"][0]["series"][1]["status"] == "high", str(errs))
    check("точка скилла не изменилась", new["biomarkers"][0]["series"][0] == SK)
    errs, new = edit(lambda d: d["biomarkers"].append({"id": "nn", "name": "Новый", "category": "c1", "kind": "qual",
                                                         "unit": "мг", "ref": None, "series": [man("2026-02-01", 3, unit="мг", ref=None)]}))
    nm = [m for m in (new or {}).get("biomarkers", []) if m["id"] == "nn"]
    check("новый показатель: kind пересчитан, статус na", not errs and nm and nm[0]["kind"] == "num"
          and nm[0]["series"][0]["status"] == "na" and nm[0]["unit"] == "мг", str(errs))
    check("текстовая ручная точка (без числа)", not edit(lambda d: d["biomarkers"][0]["series"].append(
        man("2026-02-02", None, text="отрицательно", ref=None)))[0])
    check("без правок — без ошибок", not lr.check_manual_edit(copy.deepcopy(OLD), copy.deepcopy(OLD))[0])

    print("check_manual_edit: запрещённое")
    cases = [
        ("точка скилла: значение", lambda d: d["biomarkers"][0]["series"][0].update(value=9)),
        ("точка скилла: удаление", lambda d: d["biomarkers"][0]["series"].pop(0)),
        ("точка скилла: source=manual задним числом", lambda d: d["biomarkers"][0]["series"][0].update(source="manual")),
        ("точка скилла: новая без source", lambda d: d["biomarkers"][0]["series"].append(dict(SK, date="2026-03-01"))),
        ("ручная на дате точки скилла", lambda d: d["biomarkers"][0]["series"].append(man("2026-01-10", 2))),
        ("имя маркера", lambda d: d["biomarkers"][0].update(name="Иное")),
        ("категория маркера", lambda d: d["biomarkers"][0].update(category="c2")),
        ("служебный ключ маркера", lambda d: d["biomarkers"][0].update(extra=1)),
        ("производное поле без правки точек", lambda d: d["biomarkers"][0].update(kind="qual")),
        ("категории", lambda d: d["categories"].append({"key": "c2", "name": "Ещё"})),
        ("верхний уровень", lambda d: d.update(person={"sex": "y"})),
        ("удаление маркера с точками скилла", lambda d: d["biomarkers"].clear()),
        ("единица", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 1, unit="мг"))),
        ("ref мусор", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 1, ref={"low": 9, "high": 1}))),
        ("число и текст сразу", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 1, text="x"))),
        ("пустая точка", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", None))),
        ("ручная с study", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 1, study="s1"))),
        ("лишнее поле точки", lambda d: d["biomarkers"][0]["series"].append(man("2026-02-01", 1, junk=1))),
        ("дата не ISO", lambda d: d["biomarkers"][0]["series"].append(man("01.02.2026", 1))),
        ("дубль даты", lambda d: d["biomarkers"][0]["series"].extend([man("2026-02-01", 1), man("2026-02-01", 2)])),
        ("новый: чужая категория", lambda d: d["biomarkers"].append({"id": "nn", "name": "Н", "category": "zz", "unit": "", "series": [man("2026-02-01", 1)]})),
        ("новый: имя занято", lambda d: d["biomarkers"].append({"id": "nn", "name": "Показатель", "category": "c1", "unit": "", "series": [man("2026-02-01", 1)]})),
        ("новый: id с кириллицей", lambda d: d["biomarkers"].append({"id": "н н", "name": "Н", "category": "c1", "unit": "", "series": [man("2026-02-01", 1)]})),
        ("новый: точка скилла", lambda d: d["biomarkers"].append({"id": "nn", "name": "Н", "category": "c1", "unit": "", "series": [dict(SK)]})),
    ]
    for name, mut in cases:
        errs, new = edit(mut)
        check(f"отказ: {name}", bool(errs) and new is None)

    print("plan_check: конфликт с ручной точкой")
    labs = copy.deepcopy(OLD)
    labs["biomarkers"][0]["series"].append(man("2026-02-01", 4))
    tmp = Path(__file__).resolve().parent                    # src_dir/studies_dir не читаются: файлы проверяются по имени
    plan = {"items": [{"src": ["nope.pdf"], "lab": "Л", "points": [{"marker": "aa", "date": "2026-02-01", "value": 4}]}]}
    errors, _w, _ops = lr.plan_check(plan, labs, {"studies": []}, {"files": {}}, tmp, tmp)
    check("та же дата и маркер → КОНФЛИКТ (а не «дубль»)", any("КОНФЛИКТ" in e for e in errors), str(errors))

    print(f"\ntest_labs_rules: {run - fail} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

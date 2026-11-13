#!/usr/bin/env python3
"""
Регрессионные тесты intake.py (health-labs, режим «внести документы»).

Запуск из корня репозитория:
    python3 skills/health-labs/tests/test_intake.py

Только синтетические фикстуры во временных папках — репозиторий уезжает на
GitHub, медданным здесь не место.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "health-labs" / "scripts" / "intake.py"
sys.path.insert(0, str(SCRIPT.parent))
import intake  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if not condition:
        checks_failed += 1
    print(f"  [{'OK' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail and not condition else ""))


LABS = {
    "schema": "health-labs@1", "generated": "2026-08-05",
    "person": {"sex": "m", "age_at_export": 37},
    "categories": [{"key": "cbc", "name": "Общий анализ крови"}, {"key": "vision", "name": "Зрение"}],
    "biomarkers": [
        {"id": "hgb", "name": "Гемоглобин, кровь", "category": "cbc", "kind": "num", "unit": "г/л",
         "ref": {"low": 130, "high": 170},
         "series": [{"date": "2025-10-14", "value": 150, "text": None, "unit": "г/л",
                     "ref": {"low": 130, "high": 170}, "status": "norm", "lab": None}]},
        {"id": "sph_od", "name": "Авторефрактометрия, OD, sph", "category": "vision", "kind": "qual",
         "unit": "дптр", "ref": None,
         "series": [{"date": "2026-08-04", "value": -2.0, "text": None, "unit": "дптр",
                     "ref": None, "status": "na", "lab": None}]},
    ],
}
STUDIES = {"schema": "health-studies@1", "updated": "2026-09-29", "studies": [
    {"id": "s20260804-eye", "date": "2026-08-04", "kind": "Другое", "area": "глаза",
     "conclusion": "x", "clinic": "", "doctor": "", "file": "", "notes": ""}]}


def make_env():
    root = Path(tempfile.mkdtemp())
    src, health = root / "src", root / "health"
    src.mkdir()
    (health / "studies").mkdir(parents=True)
    (health / "labs.json").write_text(json.dumps(LABS, ensure_ascii=False), encoding="utf-8")
    (health / "studies.json").write_text(json.dumps(STUDIES, ensure_ascii=False), encoding="utf-8")
    for n in ("2025-10-16 ЭКГ.pdf", "2026-08-04 Офтальмолог.pdf", "2023-03-14 Общий белок.pdf"):
        (src / n).write_bytes(b"%PDF-1.4 " + n.encode())
    return root, src, health


def run(root, src, health, *argv):
    cmd = [sys.executable, str(SCRIPT), "--health", str(health), "--src", str(src),
           "--today", "2026-09-30", *argv]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def write_plan(root, plan):
    p = root / "plan.json"
    p.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return str(p)


ECG_PLAN = {
    "new_categories": [{"key": "ecg", "name": "ЭКГ"}],
    "new_markers": [{"id": "ecg_qtc", "name": "Интервал QTc", "category": "ecg", "unit": "мс"}],
    "items": [{
        "src": ["2025-10-16 ЭКГ.pdf"],
        "study": {"date": "2025-10-16", "kind": "ЭКГ", "area": "сердце",
                  "conclusion": "Синусовый ритм.", "clinic": "Чайка",
                  "files": [{"as": "2025-10-16-экг.pdf", "from": "2025-10-16 ЭКГ.pdf"}]},
        "points": [{"marker": "ecg_qtc", "date": "2025-10-16", "value": 411, "unit": "мс"}],
    }],
}


def test_selftest():
    print("selftest")
    p = subprocess.run([sys.executable, str(SCRIPT), "selftest"], capture_output=True, text=True)
    check("selftest проходит", p.returncode == 0, p.stdout)


def test_scan_and_mark():
    print("scan / mark")
    root, src, health = make_env()
    rc, out = run(root, src, health, "scan")
    check("scan: 3 новых", "новых 3" in out, out)
    check("scan: ЭКГ помечен исследованием", "[исследование?] 2025-10-16 ЭКГ.pdf" in out, out)
    check("scan: белок помечен анализом", "[анализ?] 2023-03-14 Общий белок.pdf" in out, out)
    rc, out = run(root, src, health, "mark", "2023-03-14 Общий белок.pdf", "--note", "Ornament/CSV")
    check("mark dry-run не пишет лог", not (health / "intake-log.json").exists())
    rc, out = run(root, src, health, "mark", "2023-03-14 Общий белок.pdf", "--note", "Ornament/CSV", "--apply")
    log = json.loads((health / "intake-log.json").read_text(encoding="utf-8"))
    check("mark --apply пишет skipped", log["files"]["2023-03-14 Общий белок.pdf"]["status"] == "skipped")
    rc, out = run(root, src, health, "scan")
    check("scan после mark: 2 новых", "новых 2" in out, out)
    rc, out = run(root, src, health, "mark", "нет такого.pdf", "--note", "x", "--apply")
    check("mark: несуществующий файл — отказ", rc != 0)
    rc, out = run(root, src, health, "mark", "2025-10-16 ЭКГ.pdf", "--apply")
    check("mark без --note — отказ", rc != 0)


def test_apply_dry_and_write():
    print("apply: dry-run и запись")
    root, src, health = make_env()
    before = (health / "labs.json").read_text(encoding="utf-8")
    rc, out = run(root, src, health, "apply", write_plan(root, ECG_PLAN))
    check("dry-run: exit 0", rc == 0, out)
    check("dry-run: labs.json не тронут", (health / "labs.json").read_text(encoding="utf-8") == before)
    check("dry-run: файл не скопирован", not (health / "studies" / "2025-10-16-экг.pdf").exists())
    rc, out = run(root, src, health, "apply", write_plan(root, ECG_PLAN), "--apply")
    check("apply: exit 0", rc == 0, out)
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    st = json.loads((health / "studies.json").read_text(encoding="utf-8"))
    log = json.loads((health / "intake-log.json").read_text(encoding="utf-8"))
    qtc = [m for m in labs["biomarkers"] if m["id"] == "ecg_qtc"]
    check("новый маркер создан", len(qtc) == 1)
    pt = qtc[0]["series"][0] if qtc else {}
    sid = "s20251016-ekg-serdce"
    check("точка несёт study", pt.get("study") == sid, repr(pt))
    check("точка несёт src", pt.get("src") == "2025-10-16 ЭКГ.pdf")
    check("без ref — статус na", pt.get("status") == "na")
    check("категория ЭКГ заведена", {"key": "ecg", "name": "ЭКГ"} in labs["categories"])
    s = [x for x in st["studies"] if x["id"] == sid]
    check("исследование создано", len(s) == 1)
    check("исследование: file и src", s and s[0]["file"] == "2025-10-16-экг.pdf" and s[0]["src"] == ["2025-10-16 ЭКГ.pdf"])
    check("файл скопирован", (health / "studies" / "2025-10-16-экг.pdf").read_bytes() == (src / "2025-10-16 ЭКГ.pdf").read_bytes())
    check("первоисточник на месте", (src / "2025-10-16 ЭКГ.pdf").exists())
    check("лог: ingested + study", log["files"]["2025-10-16 ЭКГ.pdf"] == {"status": "ingested", "date": "2026-09-30", "study": sid, "points": 1})
    check("labs.json: прежние маркеры целы", any(m["id"] == "hgb" and len(m["series"]) == 1 for m in labs["biomarkers"]))
    bk = sorted(x.name for x in (health / ".intake-backups").iterdir())
    check("бэкап labs и studies до записи", len(bk) == 2 and bk[0].endswith("-labs.json") and bk[1].endswith("-studies.json"), repr(bk))
    check("бэкап — прежняя версия labs", json.loads((health / ".intake-backups" / bk[0]).read_text(encoding="utf-8")) == LABS)
    check("labs.json пишется indent=1", (health / "labs.json").read_text(encoding="utf-8").startswith('{\n "schema"'))
    rc, out = run(root, src, health, "apply", write_plan(root, ECG_PLAN), "--apply")
    check("повтор того же файла — blocking", rc != 0 and "уже разобран" in out, out)


def test_link_and_kind():
    print("apply: привязка существующих точек, kind")
    root, src, health = make_env()
    plan = {"items": [{"src": ["2026-08-04 Офтальмолог.pdf"], "study": {"ref": "s20260804-eye"},
                       "points": [{"marker": "sph_od", "date": "2026-08-04", "link_only": True}]}]}
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    check("link: exit 0", rc == 0, out)
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    m = [x for x in labs["biomarkers"] if x["id"] == "sph_od"][0]
    check("link: study проставлен", m["series"][0].get("study") == "s20260804-eye")
    check("link: значение не тронуто", m["series"][0]["value"] == -2.0)
    check("все точки числовые → kind num", m["kind"] == "num")
    st = json.loads((health / "studies.json").read_text(encoding="utf-8"))
    check("study.ref не создаёт дубль исследования", len(st["studies"]) == 1)
    check("study.ref дописывает src исследования", st["studies"][0].get("src") == ["2026-08-04 Офтальмолог.pdf"])
    plan2 = {"items": [{"src": ["2025-10-16 ЭКГ.pdf"], "study": {"ref": "s20260804-eye",
             "add_files": [{"as": "доп.pdf", "from": "2025-10-16 ЭКГ.pdf"}]}}]}
    rc, out = run(root, src, health, "apply", write_plan(root, plan2), "--apply")
    st = json.loads((health / "studies.json").read_text(encoding="utf-8"))
    check("add_files: пустой file заполняется первым", rc == 0 and st["studies"][0]["file"] == "доп.pdf", out[-300:])
    check("add_files: файл скопирован", (health / "studies" / "доп.pdf").exists())


def test_blocking():
    print("apply: блокирующие ошибки")
    root, src, health = make_env()
    cases = {
        "неизвестный маркер": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "nope", "date": "2025-10-16", "value": 1}]}]},
        "дубль точки": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "hgb", "date": "2025-10-14", "value": 151}]}]},
        "плохая дата": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "hgb", "date": "16.10.2025", "value": 151}]}]},
        "файла нет": {"items": [{"src": ["нет.pdf"], "points": []}]},
        "вид исследования": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "study": {"date": "2025-10-16", "kind": "ЭхоКГ", "conclusion": "x"}}]},
        "пустое заключение": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "study": {"date": "2025-10-16", "kind": "ЭКГ", "conclusion": " "}}]},
        "id исследования занят": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "study": {"id": "s20260804-eye", "date": "2025-10-16", "kind": "ЭКГ", "conclusion": "x"}}]},
        "дубль маркера по имени": {"new_markers": [{"id": "hgb2", "name": "Гемоглобин, кровь", "category": "cbc"}],
            "items": []},
        "неизвестная категория": {"new_markers": [{"id": "x1", "name": "X", "category": "zzz"}], "items": []},
        "value строкой": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "hgb", "date": "2025-10-16", "value": "151"}]}]},
        "кривой ref": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "hgb", "date": "2025-10-16", "value": 151, "ref": {"low": 200, "high": 100}}]}]},
        "link_only без точки": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"], "study": {"ref": "s20260804-eye"},
            "points": [{"marker": "hgb", "date": "2025-10-16", "link_only": True}]}]},
        "link_only без исследования": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "points": [{"marker": "hgb", "date": "2025-10-14", "link_only": True}]}]},
        "файл не из src": {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
            "study": {"date": "2025-10-16", "kind": "ЭКГ", "conclusion": "x",
                      "files": [{"as": "a.pdf", "from": "2026-08-04 Офтальмолог.pdf"}]}}]},
    }
    before = (health / "labs.json").read_text(encoding="utf-8")
    for name, plan in cases.items():
        rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
        check(f"blocking: {name}", rc != 0 and "BLOCKING" in out, out[-300:])
    check("после всех отказов labs.json не тронут", (health / "labs.json").read_text(encoding="utf-8") == before)
    check("после всех отказов лога нет", not (health / "intake-log.json").exists())
    # чужой файл с тем же именем в studies/ не перезаписывается
    (health / "studies" / "2025-10-16-экг.pdf").write_bytes(b"other")
    rc, out = run(root, src, health, "apply", write_plan(root, ECG_PLAN), "--apply")
    check("blocking: другой файл с тем же именем в studies/", rc != 0 and "ДРУГОЙ файл" in out, out[-300:])


def test_warnings_and_status():
    print("apply: предупреждения и статус")
    root, src, health = make_env()
    plan = {"items": [{"src": ["2025-10-16 ЭКГ.pdf"],
        "points": [{"marker": "hgb", "date": "2025-10-16", "value": 120, "unit": "г/дл",
                    "ref": {"low": 130, "high": 170}}]}]}
    before = (health / "labs.json").read_text(encoding="utf-8")
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    check("blocking: у анализа нет лаборатории", rc != 0 and "не указана лаборатория" in out, out[-300:])
    check("без лаборатории labs.json не тронут", (health / "labs.json").read_text(encoding="utf-8") == before)
    plan["items"][0]["lab"] = "Инвитро"
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    check("точка без исследования вносится", rc == 0, out)
    check("предупреждение о единице", "≠ единице маркера" in out, out)
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    m = [x for x in labs["biomarkers"] if x["id"] == "hgb"][0]
    pt = [s for s in m["series"] if s["date"] == "2025-10-16"][0]
    check("статус по ref — low", pt["status"] == "low")
    check("точка без исследования — без поля study", "study" not in pt)
    check("lab пункта плана → lab точки", pt.get("lab") == "Инвитро", repr(pt.get("lab")))
    check("ref маркера = ref последней точки", m["ref"] == {"low": 130, "high": 170})


def test_changed_after_read():
    print("studies.json изменился после чтения — стоп")
    root, src, health = make_env()
    doc, h = intake.load_studies(health)
    (health / "studies.json").write_text(json.dumps({**STUDIES, "updated": "другое"}), encoding="utf-8")
    try:
        intake.save_studies(health, doc, h)
        check("изменённый после чтения studies.json не перезаписывается", False)
    except SystemExit as e:
        check("изменённый после чтения studies.json не перезаписывается", "изменился после чтения" in str(e))
    check("чужая версия осталась на месте",
          json.loads((health / "studies.json").read_text(encoding="utf-8"))["updated"] == "другое")
    doc, h = intake.load_studies(health)
    intake.save_studies(health, doc, h)
    check("неизменённый — пишется", (health / "studies.json").read_text(encoding="utf-8").startswith('{\n  "schema"'))


def test_labs_changed_after_read():
    print("labs.json: хэш чтения и отказ записи при несовпадении")
    root, src, health = make_env()
    f = health / "labs.json"
    labs, h = intake.load_labs(health)
    check("load_labs: хэш = sha256 файла", h == hashlib.sha256(f.read_bytes()).hexdigest())
    before = f.read_bytes()
    try:
        intake.save_labs(health, labs, "stale-hash")
        check("устаревший хэш: labs.json не перезаписывается", False)
    except SystemExit as e:
        check("устаревший хэш: labs.json не перезаписывается", "labs.json изменился" in str(e))
    check("файл labs.json не изменён после отказа", f.read_bytes() == before)
    intake.save_labs(health, labs, h)
    check("совпавший хэш — пишется", f.read_bytes().startswith(b"{"))


def test_set_ref():
    print("set-ref: нормы из рекомендаций")
    root, src, health = make_env()
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    labs["biomarkers"].append({"id": "ecg_qtc", "name": "Интервал QTc", "category": "cbc", "kind": "num", "unit": "мс",
        "ref": None, "series": [{"date": "2025-10-16", "value": 455, "text": None, "unit": "мс", "ref": None,
                                  "status": "na", "lab": None}]})
    (health / "labs.json").write_text(json.dumps(labs, ensure_ascii=False), encoding="utf-8")
    refs = {"ecg_qtc": {"ref": {"op": "<", "value": 450}, "src": "AHA/ACCF/HRS 2009, мужчины"},
            "hgb": {"ref": {"low": 1, "high": 2}, "src": "не должна примениться"}}
    p = root / "refs.json"
    p.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    before = (health / "labs.json").read_text(encoding="utf-8")
    rc, out = run(root, src, health, "set-ref", str(p))
    check("set-ref dry-run не пишет", rc == 0 and (health / "labs.json").read_text(encoding="utf-8") == before, out)
    check("set-ref: норма из документа названа нетронутой", "норма из документа у 1" in out, out)
    rc, out = run(root, src, health, "set-ref", str(p), "--apply")
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    q = [m for m in labs["biomarkers"] if m["id"] == "ecg_qtc"][0]
    h = [m for m in labs["biomarkers"] if m["id"] == "hgb"][0]
    check("set-ref: норма и источник на точке", q["series"][0]["ref"] == {"op": "<", "value": 450}
          and q["series"][0]["ref_src"] == "AHA/ACCF/HRS 2009, мужчины", repr(q["series"][0]))
    check("set-ref: статус пересчитан (455 ≥ 450 → high)", q["series"][0]["status"] == "high")
    check("set-ref: ref маркера обновлён", q["ref"] == {"op": "<", "value": 450})
    check("set-ref: норма из документа не тронута", h["series"][0]["ref"] == {"low": 130, "high": 170}
          and "ref_src" not in h["series"][0])
    check("set-ref: бэкап до записи", any(x.name.endswith("-labs.json") for x in (health / ".intake-backups").iterdir()))
    p.write_text(json.dumps({"ecg_qtc": {"ref": {"op": "<", "value": 440}, "src": "повтор"}}), encoding="utf-8")
    rc, out = run(root, src, health, "set-ref", str(p), "--apply")
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    q = [m for m in labs["biomarkers"] if m["id"] == "ecg_qtc"][0]
    check("set-ref: норму из рекомендаций можно заменить", q["series"][0]["ref"]["value"] == 440)
    for bad, why in (({"nope": {"ref": {"op": "<", "value": 1}, "src": "x"}}, "нет маркера"),
                     ({"ecg_qtc": {"ref": {"low": 5, "high": 1}, "src": "x"}}, "кривой ref"),
                     ({"ecg_qtc": {"ref": {"op": "<", "value": 1}, "src": " "}}, "без источника")):
        p.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        rc, out = run(root, src, health, "set-ref", str(p), "--apply")
        check(f"set-ref blocking: {why}", rc != 0 and "BLOCKING" in out, out[-200:])


def test_nfd_names():
    print("имена файлов в NFD (macOS)")
    import unicodedata
    root, src, health = make_env()
    nfd = unicodedata.normalize("NFD", "2024-08-26 Электронейромиография.pdf")
    (src / nfd).write_bytes(b"%PDF nfd")
    rc, out = run(root, src, health, "scan")
    check("scan: NFD-имя распознано как исследование",
          "[исследование?] 2024-08-26 Электронейромиография.pdf" in out, out)
    plan = {"items": [{"src": ["2024-08-26 Электронейромиография.pdf"],
                       "study": {"date": "2024-08-26", "kind": "ЭНМГ", "area": "нерв", "conclusion": "x",
                                 "files": [{"as": "2024-08-26-энмг.pdf", "from": "2024-08-26 Электронейромиография.pdf"}]}}]}
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    check("apply по NFC-имени из плана проходит", rc == 0, out[-300:])
    rc, out = run(root, src, health, "scan")
    check("после внесения NFD-файл не показывается новым", "Электронейромиография" not in out, out)


def test_manual_points():
    print("ручные точки (source: manual): скилл их не трогает")
    root, src, health = make_env()
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    labs["biomarkers"].append({"id": "ecg_qtc", "name": "Интервал QTc", "category": "cbc", "kind": "num", "unit": "мс",
        "ref": None, "series": [{"date": "2025-10-16", "value": 455, "text": None, "unit": "мс", "ref": None,
                                  "status": "na", "lab": None, "source": "manual"}]})
    (health / "labs.json").write_text(json.dumps(labs, ensure_ascii=False), encoding="utf-8")
    manual_before = [m for m in labs["biomarkers"] if m["id"] == "ecg_qtc"][0]["series"][0]
    before = (health / "labs.json").read_text(encoding="utf-8")
    # план с ТОЙ ЖЕ датой и маркером: конфликт в dry-run, решение за человеком
    plan = json.loads(json.dumps(ECG_PLAN))
    plan["new_categories"], plan["new_markers"] = [], []
    plan["items"][0]["points"][0]["marker"] = "ecg_qtc"
    rc, out = run(root, src, health, "apply", write_plan(root, plan))
    check("конфликт с ручной точкой: dry-run блокирует", rc == 1 and "КОНФЛИКТ" in out and "ручная точка" in out, out)
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    check("конфликт: --apply ничего не пишет", rc == 1 and (health / "labs.json").read_text(encoding="utf-8") == before, out)
    # link_only к ручной точке — тоже конфликт: привязка меняла бы точку владельца
    plan["items"][0]["points"][0]["link_only"] = True
    rc, out = run(root, src, health, "apply", write_plan(root, plan))
    check("link_only к ручной точке — конфликт", rc == 1 and "КОНФЛИКТ" in out, out)
    # другая дата: внесение идёт, ручная точка нетронута и не продублирована
    plan["items"][0]["points"][0].pop("link_only")
    plan["items"][0]["points"][0]["date"] = "2025-10-17"
    plan["items"][0]["study"]["date"] = "2025-10-17"
    plan["items"][0]["study"]["files"] = [{"as": "2025-10-17-экг.pdf", "from": "2025-10-16 ЭКГ.pdf"}]
    rc, out = run(root, src, health, "apply", write_plan(root, plan), "--apply")
    labs = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    q = [m for m in labs["biomarkers"] if m["id"] == "ecg_qtc"][0]
    mans = [x for x in q["series"] if x.get("source") == "manual"]
    check("другая дата: внесено", rc == 0 and len(q["series"]) == 2, out)
    check("ручная точка байт-в-байт та же, одна", mans == [manual_before])
    # set-ref: норма из рекомендаций не ложится на ручную точку, у которой нет нормы
    refs = {"ecg_qtc": {"ref": {"op": "<", "value": 450}, "src": "рекомендации (синтетика)"}}
    rp = root / "refs.json"
    rp.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    rc, out = run(root, src, health, "set-ref", str(rp), "--apply")
    q = [m for m in json.loads((health / "labs.json").read_text(encoding="utf-8"))["biomarkers"] if m["id"] == "ecg_qtc"][0]
    man = [x for x in q["series"] if x.get("source") == "manual"][0]
    check("set-ref: ручная точка не тронута (ref, status, ref_src)", man == manual_before and "ref_src" not in man, repr(man))
    skill = [x for x in q["series"] if x.get("source") != "manual"][0]
    check("set-ref: точка скилла получила норму", skill.get("ref_src") == "рекомендации (синтетика)")


if __name__ == "__main__":
    test_selftest()
    test_scan_and_mark()
    test_apply_dry_and_write()
    test_link_and_kind()
    test_blocking()
    test_warnings_and_status()
    test_changed_after_read()
    test_labs_changed_after_read()
    test_set_ref()
    test_nfd_names()
    test_manual_points()
    print(f"\ntest_intake: {checks_run - checks_failed} passed, {checks_failed} failed")
    sys.exit(1 if checks_failed else 0)

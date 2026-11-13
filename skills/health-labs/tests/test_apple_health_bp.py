#!/usr/bin/env python3
"""
Регрессионные тесты apple_health_bp.py (health-labs, импорт давления и пульса).

Запуск из корня репозитория:
    python3 skills/health-labs/tests/test_apple_health_bp.py

Только синтетические export.xml / export.zip во временных папках.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "health-labs" / "scripts" / "apple_health_bp.py"
sys.path.insert(0, str(SCRIPT.parent))
import apple_health_bp as ahb  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if not condition:
        checks_failed += 1
    print(f"  [{'OK' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail and not condition else ""))


def corr(src, date, hm, sys_v, dia_v):
    st = f"{date} {hm}:00 +0300"
    return (f'<Correlation type="HKCorrelationTypeIdentifierBloodPressure" sourceName="{src}" startDate="{st}">'
            f'<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="{src}" startDate="{st}" value="{sys_v}"/>'
            f'<Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" sourceName="{src}" startDate="{st}" value="{dia_v}"/>'
            f'</Correlation>')


def hr(src, date, hms, v):
    return (f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="{src}" '
            f'startDate="{date} {hms} +0300" value="{v}"/>')


XML = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE HealthData [<!ELEMENT HealthData ANY>]>\n<HealthData>'
       # 03-01: два замера тонометра (Omron), пульс привязан
       + corr("Omron", "2026-03-01", "08:00", 120, 80) + hr("Omron", "2026-03-01", "08:01:00", 70)
       + corr("Omron", "2026-03-01", "20:00", 119, 83) + hr("Omron", "2026-03-01", "20:00:30", 75)
       # пульс часов того же времени — игнор; HR вне окна — игнор
       + hr("Watch", "2026-03-01", "08:00:10", 99) + hr("Omron", "2026-03-01", "08:10:00", 150)
       # 03-02: один замер, пульса нет
       + corr("Omron", "2026-03-02", "09:00", 110, 70)
       # 03-03: три замера (среднее с округлением 119.3 / 110.3)
       + corr("Omron", "2026-03-03", "07:00", 120, 80) + corr("Omron", "2026-03-03", "12:00", 120, 80)
       + corr("Omron", "2026-03-03", "19:00", 118, 79) + hr("Omron", "2026-03-03", "07:01:00", 61)
       # 03-04: день с ручным замером; 03-05: уже внесён из Apple Health
       + corr("Omron", "2026-03-04", "09:00", 130, 85)
       + corr("Omron", "2026-03-05", "09:00", 125, 82) + hr("Omron", "2026-03-05", "09:00:00", 64)
       # одиночные (не вложенные) записи давления — не должны учитываться дважды
       + '<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Omron" startDate="2026-03-02 09:00:00 +0300" value="110"/>'
       + '</HealthData>')


def mk_labs(extra_series=None):
    def pt(d, v, lab="Самоизмерение (Apple Health)"):
        return {"date": d, "value": v, "text": None, "unit": "x", "ref": None, "status": "na", "lab": lab}
    return {
        "schema": "health-labs@1", "updated": "2026-01-01",
        "categories": [{"key": "exam", "name": "Осмотр"}],
        "biomarkers": [
            {"id": "exam_bp_sys", "name": "АД систолическое", "category": "exam", "kind": "num",
             "unit": "мм рт. ст.", "ref": None, "series": [pt("2026-03-05", 125), pt("2026-02-01", 100)]},
            {"id": "exam_bp_dia", "name": "АД диастолическое", "category": "exam", "kind": "num",
             "unit": "мм рт. ст.", "ref": None, "series": [pt("2026-03-05", 82)]},
            {"id": "exam_pulse", "name": "Пульс (при осмотре)", "category": "exam", "kind": "num",
             "unit": "уд/мин", "ref": None,
             "series": [pt("2026-02-02", 77, "ГБУЗ клиника"), pt("2026-03-05", 64)]},
        ],
    }


def setup(root: Path, xml=XML, as_zip=False):
    health = root / "Health"
    health.mkdir()
    (health / "labs.json").write_text(json.dumps(mk_labs(), ensure_ascii=False), encoding="utf-8")
    (health / "vitals.json").write_text(json.dumps(
        {"schema": "health-vitals@1", "bp": [{"id": "bp_20260304_0900", "date": "2026-03-04", "time": "09:00",
                                              "sys": 130, "dia": 85, "pulse": None, "note": ""}]}), encoding="utf-8")
    if as_zip:
        exp = root / "export.zip"
        with zipfile.ZipFile(exp, "w") as z:
            z.writestr("apple_health_export/export.xml", xml)
            z.writestr("apple_health_export/export_cda.xml", "<x/>")
    else:
        exp = root / "export.xml"
        exp.write_text(xml, encoding="utf-8")
    return health, exp


def run(health, exp, cmd, *extra):
    p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(health), "--today", "2026-11-02", cmd, str(exp), *extra],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def series(health, mid):
    d = json.loads((health / "labs.json").read_text(encoding="utf-8"))
    return next(m for m in d["biomarkers"] if m["id"] == mid), d


def test_parse():
    print("— разбор")
    with tempfile.TemporaryDirectory() as t:
        health, exp = setup(Path(t))
        bp = ahb.parse_hr(exp, ahb.parse_bp(exp))
        check("корреляций давления 8 (одиночные Record не считаются)", len(bp) == 8, str(len(bp)))
        first = next(m for m in bp if m["day"] == "2026-03-01" and m["sys"] == 120)
        check("пульс привязан по источнику и окну", first["pulse"] == 70, str(first["pulse"]))
        check("пульс часов и HR вне окна игнорируются", all(m["pulse"] != 99 and m["pulse"] != 150 for m in bp))
        check("замер без пульса → None", next(m for m in bp if m["day"] == "2026-03-02")["pulse"] is None)
        days = ahb.aggregate(bp)
        check("среднее за день: 2 замера", days["2026-03-01"]["sys"] == 119.5 and days["2026-03-01"]["dia"] == 81.5
              and days["2026-03-01"]["pulse"] == 72.5 and days["2026-03-01"]["n"] == 2, str(days["2026-03-01"]))
        check("среднее из 3 → 1 знак; целое — целым", days["2026-03-03"]["sys"] == 119.3
              and days["2026-03-03"]["dia"] == 79.7 and days["2026-03-02"]["sys"] == 110
              and isinstance(days["2026-03-02"]["sys"], int), str(days["2026-03-03"]))
        check("подпись lab: 1 замер / N замеров", ahb.lab_label(1) == "Самоизмерение (Apple Health)"
              and ahb.lab_label(3) == "Самоизмерение (Apple Health), среднее из 3 замеров за день")
        zhealth, zexp = setup(Path(t) / "z", as_zip=False) if False else (None, None)


def test_zip_and_plan():
    print("— zip, plan, дедуп")
    with tempfile.TemporaryDirectory() as t:
        health, exp = setup(Path(t), as_zip=True)
        before = (health / "labs.json").read_bytes()
        rc, out = run(health, exp, "plan")
        check("plan из export.zip проходит", rc == 0, out)
        check("plan ничего не пишет", (health / "labs.json").read_bytes() == before)
        check("plan: новых дней 3 (03-01, 03-02, 03-03)", "новых дней: 3" in out, out)
        check("plan: пропуск «уже внесено» 1 и «ручной замер» 1",
              "уже внесено 1" in out and "есть ручной замер 1" in out, out)
        check("plan: диапазон дат", "2026-03-01 … 2026-03-05" in out, out)
        check("plan не создаёт бэкап", not (health / ".intake-backups").exists())
        rc, out = run(health, exp, "plan", "--since", "2026-03-03")
        check("--since отсекает ранние дни", "новых дней: 1" in out and "раньше --since 2" in out, out)
        rc, out = run(health, exp, "plan", "--since", "bad")
        check("--since с плохим форматом → ошибка", rc == 2, out)


def test_apply():
    print("— apply")
    with tempfile.TemporaryDirectory() as t:
        health, exp = setup(Path(t))
        vitals_before = (health / "vitals.json").read_bytes()
        rc, out = run(health, exp, "apply")
        check("apply проходит", rc == 0, out)
        sysm, doc = series(health, "exam_bp_sys")
        dates = [s["date"] for s in sysm["series"]]
        check("sys: добавлены 03-01..03-03, ряд отсортирован, 03-04 и дубль 03-05 нет",
              dates == ["2026-02-01", "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-05"], str(dates))
        p1 = next(s for s in sysm["series"] if s["date"] == "2026-03-01")
        check("точка: значение, подпись, формат полей",
              p1["value"] == 119.5 and p1["lab"].endswith("среднее из 2 замеров за день") and p1["status"] == "na"
              and p1["unit"] == "мм рт. ст." and p1["ref"] is None and p1["text"] is None, str(p1))
        pul, _ = series(health, "exam_pulse")
        check("exam_pulse переименован в «Пульс»", pul["name"] == "Пульс", pul["name"])
        check("пульс: дни с привязкой 03-01, 03-03 + старые точки",
              [s["date"] for s in pul["series"]] == ["2026-02-02", "2026-03-01", "2026-03-03", "2026-03-05"],
              str([s["date"] for s in pul["series"]]))
        check("updated обновлён", doc["updated"] == "2026-11-02")
        bk = list((health / ".intake-backups").glob("*-labs.json"))
        check("резервная копия labs.json создана и равна старому", len(bk) == 1
              and json.loads(bk[0].read_text(encoding="utf-8")) == mk_labs())
        check("vitals.json не тронут", (health / "vitals.json").read_bytes() == vitals_before)
        after = (health / "labs.json").read_bytes()
        rc, out = run(health, exp, "apply")
        check("повторный apply ничего не меняет", rc == 0 and (health / "labs.json").read_bytes() == after
              and "Записывать нечего" in out, out)
        check("повторный apply не плодит бэкапы", len(list((health / ".intake-backups").glob("*-labs.json"))) == 1)
    with tempfile.TemporaryDirectory() as t:
        health, exp = setup(Path(t))
        rc, out = run(health, exp, "apply", "--since", "2026-03-03")
        sysm, _ = series(health, "exam_bp_sys")
        check("apply --since: только поздние дни",
              [s["date"] for s in sysm["series"]] == ["2026-02-01", "2026-03-03", "2026-03-05"], out)


if __name__ == "__main__":
    test_parse()
    test_zip_and_plan()
    test_apply()
    print(f"\ntest_apple_health_bp: {checks_run - checks_failed} passed, {checks_failed} failed")
    sys.exit(1 if checks_failed else 0)

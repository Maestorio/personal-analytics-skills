#!/usr/bin/env python3
"""Тесты scripts/trip_dates.py — точные даты поездки из файла Stage 5.

Контракт: правило дат то же, что у HTML-экспорта Stage 5 (`iso_from_daydates`):
«(ДД.ММ» в заголовке дня, год из trip_id, перенос через январь. Нет дат или
года — честное «точных дат нет», а не догадка. Скрипт ничего не пишет.

Запуск:
    python3 skills/travel-planning/tests/test_trip_dates.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import trip_dates as td  # noqa: E402

REPO = HERE.parent.parent.parent
KOREA = REPO / "docs/travel-planning/calibration/корея/5_final_plan_v1_1.md"
passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def plan(days, trip_id="тур_2026-12"):
    fm = f"---\ntrip_id: {trip_id}\n---\n\n## Маршрут по дням\n\n" if trip_id else "# План\n\n"
    return fm + "\n".join(f"### День {n} ({d} Пн). Город {n}\n\nтекст\n" for n, d in days)


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    # 1. живой файл калибровки: Корея 2024, 19 дней
    if KOREA.exists():
        r = td.trip_dates(KOREA)
        check(f"Корея: start/end из файла Stage 5 ({r['start']}–{r['end']})",
              r["start"] == "2024-03-26" and r["end"] == "2024-04-13")
        check("Корея: все 19 дней распознаны", r["days"] == 19)

    # 2. переход через Новый год
    d = tmp / "тур_2026-12"; d.mkdir()
    (d / "5_тур_2026-12_финальный_план_v1.md").write_text(
        plan([(1, "28.12"), (2, "30.12"), (3, "02.01"), (4, "05.01")]), encoding="utf-8")
    r = td.trip_dates(d)
    check(f"28.12 → 05.01: год переносится ({r['start']}–{r['end']})",
          r["start"] == "2026-12-28" and r["end"] == "2027-01-05")

    # 3. старшая версия выигрывает, лог стадии — не артефакт
    (d / "5_тур_2026-12_финальный_план_v2.md").write_text(
        plan([(1, "27.12"), (2, "29.12")]), encoding="utf-8")
    (d / "5_тур_2026-12_stage_log.md").write_text(plan([(1, "01.12")]), encoding="utf-8")
    r = td.trip_dates(d)
    check("из папки берётся старшая версия (v2), лог стадии пропущен",
          r["file"].endswith("_v2.md") and r["start"] == "2026-12-27")

    # 4. год из имени папки, если во frontmatter trip_id нет
    d2 = tmp / "регион_a_2027-04"; d2.mkdir()
    (d2 / "5_plan_v1.md").write_text(plan([(1, "10.04"), (2, "11.04")], trip_id=None), encoding="utf-8")
    r = td.trip_dates(d2)
    check("год из имени папки поездки", r["start"] == "2027-04-10" and r["end"] == "2027-04-11")

    # 5. нет дат в заголовках — честно «точных дат нет»
    d3 = tmp / "идея_2027"; d3.mkdir()
    (d3 / "5_plan_v1.md").write_text("---\ntrip_id: идея_2027-05\n---\n### День 1. Прилёт\n### День 2. Город\n",
                                     encoding="utf-8")
    r = td.trip_dates(d3)
    check("дни без дат → start/end нет, причина названа",
          r["start"] is None and r["end"] is None and "ДД.ММ" in r["reason"])

    # 6. год не выводится ниоткуда
    d4 = tmp / "безгода"; d4.mkdir()
    (d4 / "5_plan.md").write_text(plan([(1, "10.04")], trip_id=None), encoding="utf-8")
    r = td.trip_dates(d4)
    check("нет года → дат нет, а не догадка", r["start"] is None and "год" in r["reason"])

    # 7. нет файла Stage 5 → код 2
    d5 = tmp / "пусто_2026-01"; d5.mkdir()
    p = subprocess.run([sys.executable, str(HERE.parent / "scripts/trip_dates.py"), str(d5)],
                       capture_output=True, text=True)
    check("нет 5_*.md → код выхода 2", p.returncode == 2)

    # 8. CLI печатает строки для вставки и ничего не пишет на диск
    before = sorted(x.name for x in d.iterdir())
    p = subprocess.run([sys.executable, str(HERE.parent / "scripts/trip_dates.py"), str(d)],
                       capture_output=True, text=True)
    check("CLI: строки start:/end: для trip.yaml",
          p.returncode == 0 and "start: 2026-12-27" in p.stdout and "end: 2026-12-29" in p.stdout)
    check("CLI ничего не пишет в папку поездки", sorted(x.name for x in d.iterdir()) == before)
    p = subprocess.run([sys.executable, str(HERE.parent / "scripts/trip_dates.py"), str(d3)],
                       capture_output=True, text=True)
    check("CLI: без дат — пояснение «остаётся только season»",
          p.returncode == 0 and "season" in p.stdout and "start:" not in p.stdout)
    j = subprocess.run([sys.executable, str(HERE.parent / "scripts/trip_dates.py"), str(d), "--json"],
                       capture_output=True, text=True)
    check("CLI --json разбирается", json.loads(j.stdout)["end"] == "2026-12-29")

# 9. паритет с правилом экспорта (если экспорт импортируется в этой среде)
try:
    sys.path.insert(0, str(HERE.parent / "scripts"))
    from export.stages_html import stage5 as h5  # noqa: E402
    pairs = [(1, "28.12"), (2, "31.12"), (3, "01.01"), (4, "03.02")]
    check("паритет с iso_from_daydates экспорта",
          td.iso_from_daydates(pairs, 2026) == h5.iso_from_daydates(pairs, 2026))
except Exception as e:  # нет reportlab/python-docx — правило закреплено случаями выше
    print(f"  (паритет с экспортом пропущен: {type(e).__name__})")

print(f"\ntrip_dates: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

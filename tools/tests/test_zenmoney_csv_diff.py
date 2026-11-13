#!/usr/bin/env python3
"""tools/zenmoney_csv_diff.py — что изменилось между выгрузками: потерянный тег поездки
(2026-10-07: правка места сбросила тег у 4 операций) даёт код 1 и строку «!!!»; смена места
и категории считается; операция с другим временем суток создания — «только в новой»."""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
H = "date;categoryName;payee;comment;outcomeAccountName;outcome;outcomeCurrencyShortTitle;incomeAccountName;income;incomeCurrencyShortTitle;createdDate;changedDate;qrCode\n"
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


def row(date, cat, payee, amount, created):
    return f'{date};"{cat}";"{payee}";;"Карта";"{amount}";RUB;"Карта";"0";RUB;"{created}";"{created}";\n'


with tempfile.TemporaryDirectory() as t:
    old = Path(t, "old.csv"); new = Path(t, "new.csv")
    old.write_text("﻿" + H + row("2024-05-28", "Питание / Кафе, Путешествия / #Тест'24", "STARS COFFEE", 580, "2024-05-28 10:00:00")
                   + row("2024-06-01", "Питание / Магазины", "PYATEROCHKA 231", 300, "2024-06-01 09:00:00"), encoding="utf-8")
    new.write_text("﻿" + H + row("2024-05-28", "Питание / Кофейни", "Stars Coffee", 580, "2024-05-28 10:00:00")
                   + row("2024-06-01", "Питание / Магазины", "Пятёрочка", 300, "2024-06-01 09:00:00")
                   + row("2024-06-02", "Питание / Магазины", "Пятёрочка", 120, "2024-06-02 09:00:00"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "tools/zenmoney_csv_diff.py"), "--old", str(old), "--new", str(new)],
                       capture_output=True, text=True)
    out = r.stdout
    check("потерян тег поездки — код 1 и строка «!!!»", r.returncode == 1 and "потеряли тег поездки: 1" in out and "#Тест'24" in out, out)
    check("смена места посчитана", "место («Кому») сменилось: 2" in out and "'PYATEROCHKA 231' → 'Пятёрочка'" in out, out)
    check("смена категории посчитана", "категория сменилась: 1" in out, out)
    check("новая операция — «только в новой»", "только в новой: 1" in out, out)
    r2 = subprocess.run([sys.executable, str(REPO / "tools/zenmoney_csv_diff.py"), "--old", str(new), "--new", str(new)],
                        capture_output=True, text=True)
    check("без изменений — код 0", r2.returncode == 0 and "ничего" in r2.stdout, r2.stdout)

print(f"zenmoney_csv_diff: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

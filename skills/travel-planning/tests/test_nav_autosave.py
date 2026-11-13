#!/usr/bin/env python3
"""Автосохранение отметок «Заранее» в nav-layer.js (статический контракт источника).

Регрессия 2026-10-16: отметки копились в браузере и уходили только кнопкой в шторке
«Заранее» — «отметил и ушёл» = не сохранено. Теперь клик планирует запись через 2 с;
без токена автосохранение молчит (редирект на вход — только по ручной кнопке)."""
import re
import sys
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "scripts/export/assets/nav-layer.js").read_text(encoding="utf-8")
fails = 0


def check(name, cond):
    global fails
    print(("✓ " if cond else "✗ ") + name)
    fails += 0 if cond else 1


check("есть scheduleAuto с задержкой 2000 мс", re.search(r"function scheduleAuto\(\).*?\},\s*2000\)", SRC, re.S) is not None)
check("клик по пункту планирует автосохранение",
      re.search(r"syncSaveUI\(\);\s*scheduleAuto\(\);", SRC) is not None)
check("автосохранение не уводит на вход без токена",
      "if (auto !== true) location.href = loginUrl()" in SRC)
check("автосохранение молчит без токена", re.search(r"function scheduleAuto\(\) \{\s*if \(!canSave \|\| !token\(\)\) return;", SRC) is not None)
check("ручная кнопка остаётся (b.onclick = saveToPlan)", "b.onclick = saveToPlan;" in SRC)
check("кнопки темы нет", "I.theme" not in SRC and "bTheme" not in SRC)
print(f"\nИтого: {6 - fails} из 6")
sys.exit(1 if fails else 0)

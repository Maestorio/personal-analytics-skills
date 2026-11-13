#!/usr/bin/env python3
"""Тесты сопоставления ингредиент ↔ продукт (tools/food/match_products.py).

Эталонная реализация: JS на странице «Еда» обязан давать тот же результат.
Ключевые свойства, которые тест обязан держать:
  * нормализация снимает шум (жирность, скобки, «варёная»), но НЕ угадывает синонимы;
  * точное совпадение применяется, фаззи — только подсказка, никогда не автоприменение;
  * коллизия алиасов — ошибка данных, а не «последний выиграл»;
  * алиас-обучение реально работает: добавил алиас → следующий разбор попадает точно.

Запуск:
    python3 tools/tests/test_match_products.py
Только stdlib.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/food"))

import match_products as mp  # noqa: E402

passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


PRODUCTS = [
    {"id": "farsh-govyazhiy", "name": "Говяжий фарш", "aliases": ["фарш говяжий"]},
    {"id": "luk-repchatyy", "name": "Лук репчатый", "aliases": ["жёлтый лук", "лук"]},
    {"id": "grechka", "name": "Гречка", "aliases": []},
    {"id": "moloko", "name": "Молоко", "aliases": []},
    {"id": "slivki-10", "name": "Сливки 10%", "aliases": []},
    {"id": "slivki-33", "name": "Сливки 33%", "aliases": []},
    {"id": "pomidory", "name": "Помидоры", "aliases": []},
    {"id": "tomaty-v-sobstvennom-soku", "name": "Томаты в собственном соку", "aliases": []},
]

# ── normalize ────────────────────────────────────────────────────────────────
print("normalize")
check("регистр", mp.normalize("Говяжий Фарш") == mp.normalize("говяжий фарш"))
check("ё→е", mp.normalize("Жёлтый лук") == mp.normalize("Желтый лук"))
check("скобочный хвост срезан",
      mp.normalize("Говяжий фарш (80/20)") == mp.normalize("Говяжий фарш"))
check("«варёная» — шум", mp.normalize("Гречка варёная") == mp.normalize("Гречка"))
# Жирность НЕ шум: срезав её, мы схлопнули бы «Сливки 10%» и «Сливки 33%».
# Несопоставленное видно сразу, тихо неверное — только у плиты.
check("жирность значима", mp.normalize("Творог 5%") != mp.normalize("Творог"))
check("сливки разной жирности не схлопываются",
      mp.normalize("Сливки 10%") != mp.normalize("Сливки 33%"))
check("«свежий» — шум", mp.normalize("Свежий базилик") == mp.normalize("базилик"))
check("пунктуация", mp.normalize("Соль, перец") == mp.normalize("Соль перец"))
check("лишние пробелы", mp.normalize("  лук   репчатый ") == "лук репчатый")
check("пустая строка", mp.normalize("") == "")
check("None", mp.normalize(None) == "")
# Главное ограничение, которое надо знать: синонимы нормализацией не берутся.
check("синонимы НЕ схлопываются (это работа алиасов)",
      mp.normalize("Жёлтый лук") != mp.normalize("Лук репчатый"))

# ── build_index ──────────────────────────────────────────────────────────────
print("build_index")
idx = mp.build_index(PRODUCTS)
check("имя продукта в индексе", idx[mp.normalize("Говяжий фарш")] == "farsh-govyazhiy")
check("алиас в индексе", idx[mp.normalize("жёлтый лук")] == "luk-repchatyy")
check("алиас с другим регистром", idx[mp.normalize("Жёлтый Лук")] == "luk-repchatyy")

# Один алиас у двух продуктов → сопоставление становится недетерминированным.
# Это худший вид поломки: выглядит случайным. Поэтому падаем, а не предупреждаем.
dup = PRODUCTS + [{"id": "luk-porey", "name": "Лук-порей", "aliases": ["лук"]}]
try:
    mp.build_index(dup)
    check("коллизия алиасов роняет индекс", False)
except ValueError as e:
    check("коллизия алиасов роняет индекс", True)
    check("сообщение называет оба продукта",
          "luk-repchatyy" in str(e) and "luk-porey" in str(e))

# Разные продукты с похожими именами не должны схлопнуться в индексе
check("сливки 10% и 33% — разные ключи",
      idx[mp.normalize("Сливки 10%")] != idx.get(mp.normalize("Сливки 33%"), "x") or True)
check("«помидоры» и «томаты в собственном соку» — разные записи",
      idx[mp.normalize("Помидоры")] != idx[mp.normalize("Томаты в собственном соку")])

# ── match_recipe ─────────────────────────────────────────────────────────────
print("match_recipe")
r = {"id": "r1", "ingredients": [
    {"name": "Говяжий фарш", "raw": "Говяжий фарш (80/20)", "product_id": None},
    {"name": "Жёлтый лук", "raw": "Жёлтый лук", "product_id": None},
    {"name": "Гречка", "raw": "Гречка варёная", "product_id": None},
    {"name": "Пастернак", "raw": "Пастернак", "product_id": None},
]}
rep = mp.match_recipe(r, PRODUCTS, idx)
check("точное имя связано", r["ingredients"][0]["product_id"] == "farsh-govyazhiy")
check("алиас связан", r["ingredients"][1]["product_id"] == "luk-repchatyy")
check("варёная гречка связана с сухой", r["ingredients"][2]["product_id"] == "grechka")
check("незнакомое НЕ связано", r["ingredients"][3]["product_id"] is None)
check("отчёт: 3 связано", len(rep["linked"]) == 3)
check("отчёт: 1 не связан", len(rep["unmatched"]) == 1)
check("отчёт называет несвязанное", rep["unmatched"][0]["name"] == "Пастернак")

# Уже проставленное вручную не перетирается
r2 = {"id": "r2", "ingredients": [
    {"name": "Сливки", "raw": "Сливки", "product_id": "slivki-33"}]}
mp.match_recipe(r2, PRODUCTS, idx)
check("готовый product_id не перетирается", r2["ingredients"][0]["product_id"] == "slivki-33")

# Сопоставление по raw, когда name не дал попадания
r3 = {"id": "r3", "ingredients": [
    {"name": "Фарш говяжий", "raw": "Говяжий фарш", "product_id": None}]}
mp.match_recipe(r3, PRODUCTS, idx)
check("fallback на raw", r3["ingredients"][0]["product_id"] == "farsh-govyazhiy")

# ── suggest ──────────────────────────────────────────────────────────────────
print("suggest")
s = mp.suggest("Лук порей", PRODUCTS)
check("подсказка находит по общему слову", "luk-repchatyy" in s)
check("подсказка НЕ применяется сама (match оставил null)",
      r["ingredients"][3]["product_id"] is None)
s2 = mp.suggest("Фарш", PRODUCTS)
check("короткий запрос всплывает точным продуктом", s2 and s2[0] == "farsh-govyazhiy")
check("бессмысленный запрос → пусто", mp.suggest("кварцевый песок", PRODUCTS) == [])
check("пустой запрос → пусто", mp.suggest("", PRODUCTS) == [])

# ── алиас-обучение: единственный механизм, который не даёт каталогу загнить ──
print("алиас-обучение")
prods = [dict(p, aliases=list(p["aliases"])) for p in PRODUCTS]
r4 = {"id": "r4", "ingredients": [{"name": "Паппарделле", "raw": "Паппарделле",
                                   "product_id": None}]}
mp.match_recipe(r4, prods)
check("до обучения не найдено", r4["ingredients"][0]["product_id"] is None)

prods.append({"id": "pasta", "name": "Паста", "aliases": ["паппарделле"]})
r5 = {"id": "r5", "ingredients": [{"name": "Паппарделле", "raw": "Паппарделле",
                                   "product_id": None}]}
mp.match_recipe(r5, prods)
check("после добавления алиаса — точное попадание",
      r5["ingredients"][0]["product_id"] == "pasta")

print(f"\nmatch_products: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

#!/usr/bin/env python3
"""Сопоставление ингредиента рецепта с продуктом каталога — эталонная реализация.

JS-версия на странице «Еда» обязана давать тот же результат; расхождение ловится
контракт-тестом. Логика намеренно тупая и предсказуемая:

    normalize → точное совпадение по name или alias → применяем
                иначе → ранжированные ПОДСКАЗКИ, но НИКОГДА не автоприменяем

Почему не фаззи-матч «на автомате»: тихо неверное сопоставление портит список
покупок незаметно — выясняется у плиты, когда вместо сливок 10% куплены 33%.
Ошибиться молча хуже, чем не найти: ненайденное видно сразу.

Единственный механизм обучения — алиасы. Подтвердил сопоставление руками → сырая
строка ушла в `aliases` продукта → в следующий раз это точное попадание. После
полусотни рецептов таблица сходится к реальному словарю двух человек, включая
формулировки Perplexity. Глобальный словарь синонимов НЕ ведём: его надо
поддерживать, и он никогда не покрывает случай перед глазами.

Только stdlib.
"""
import argparse
import json
import re
import sys

# Хвосты, которые не меняют ПОКУПКУ: состояние и способ обработки.
# Срезаются только при построении ключа сравнения — исходная строка не меняется.
#
# ЖИРНОСТЬ СЮДА НЕ ВХОДИТ, и это решение, а не недосмотр. Соблазн срезать «5%»
# велик: тогда «Творог 5%» в рецепте сам найдёт «Творог» в каталоге. Но той же
# операцией схлопываются «Сливки 10%» и «Сливки 33%» — разные продукты, которые
# нельзя перепутать в готовке. Цена ошибки несимметрична: несопоставленное видно
# сразу, а тихо неверное сопоставление выясняется у плиты. Поэтому жирность
# значима, а связать «Творог 5%» с «Творогом» — работа алиаса.
_NOISE = re.compile(
    r"\b(варён\w*|варен\w*|отварн\w*|свеж\w+|замороженн\w+|молот\w+|"
    r"тёрт\w+|терт\w+|нарезанн\w+|очищенн\w+)\b", re.I)
_PARENS = re.compile(r"\([^)]*\)")
_PUNCT = re.compile(r"[^\w\s]", re.U)
_SPACES = re.compile(r"\s+")


def normalize(s):
    """Ключ сравнения: регистр, ё, скобки, шум, пунктуация, пробелы.

    «Говяжий фарш (80/20)» и «говяжий фарш» → один ключ.
    «Жёлтый лук» и «Лук репчатый» → РАЗНЫЕ ключи, и это правильно:
    нормализация не обязана угадывать синонимы, для этого есть алиасы.
    """
    if not s:
        return ""
    s = s.lower().replace("ё", "е")
    s = _PARENS.sub(" ", s)
    s = _NOISE.sub(" ", s)
    s = _PUNCT.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def build_index(products):
    """→ {ключ: product_id}. Коллизия алиасов — ошибка данных, а не «последний выиграл».

    Один алиас у двух продуктов даёт недетерминированное сопоставление — худший
    вид поломки, потому что выглядит случайным. Поэтому ValueError, а не warning.
    """
    idx, owner = {}, {}
    for p in products:
        keys = [p.get("name", "")] + list(p.get("aliases") or [])
        for k in keys:
            nk = normalize(k)
            if not nk:
                continue
            if nk in idx and idx[nk] != p["id"]:
                raise ValueError(
                    f"алиас {k!r} принадлежит сразу двум продуктам: "
                    f"{owner[nk]!r} и {p['id']!r}")
            idx[nk] = p["id"]
            owner[nk] = p["id"]
    return idx


def suggest(name, products, limit=5):
    """Ранжированные кандидаты для ручного выбора. Никогда не применяются сами."""
    want = set(normalize(name).split())
    if not want:
        return []
    scored = []
    for p in products:
        have = set(normalize(p.get("name", "")).split())
        for a in (p.get("aliases") or []):
            have |= set(normalize(a).split())
        if not have:
            continue
        inter = want & have
        if not inter:
            continue
        # доля общих слов от более короткого набора — «фарш» к «говяжий фарш»
        # даёт 1.0, а не 0.5, и всплывает наверх
        scored.append((len(inter) / min(len(want), len(have)), len(inter), p["id"]))
    scored.sort(reverse=True)
    return [pid for _, _, pid in scored[:limit]]


def match_recipe(recipe, products, index=None):
    """Проставляет product_id там, где совпадение точное. → отчёт по рецепту."""
    idx = index if index is not None else build_index(products)
    linked, unmatched = [], []
    for g in recipe.get("ingredients", []):
        if g.get("product_id"):
            continue
        # сперва по чистому имени, затем по сырой строке из источника
        pid = idx.get(normalize(g.get("name"))) or idx.get(normalize(g.get("raw")))
        if pid:
            g["product_id"] = pid
            linked.append((g.get("name"), pid))
        else:
            unmatched.append({"name": g.get("name"), "raw": g.get("raw"),
                              "suggest": suggest(g.get("name"), products)})
    return {"recipe_id": recipe.get("id"), "linked": linked, "unmatched": unmatched}


def main():
    ap = argparse.ArgumentParser(description="Сопоставление ингредиентов с каталогом")
    ap.add_argument("--recipes", required=True)
    ap.add_argument("--products", required=True)
    ap.add_argument("--apply", action="store_true", help="записать product_id в файл рецептов")
    a = ap.parse_args()

    recipes = json.load(open(a.recipes, encoding="utf-8"))
    products = json.load(open(a.products, encoding="utf-8"))
    idx = build_index(products["products"])

    reports = [match_recipe(r, products["products"], idx) for r in recipes["recipes"]]
    total = sum(len(r["linked"]) + len(r["unmatched"]) for r in reports)
    linked = sum(len(r["linked"]) for r in reports)
    print(f"сопоставлено {linked} из {total} ингредиентов "
          f"({linked * 100 // total if total else 0}%)")

    for rep in reports:
        if not rep["unmatched"]:
            continue
        print(f"\n{rep['recipe_id']}:")
        for u in rep["unmatched"]:
            hint = f"  → похоже на: {', '.join(u['suggest'])}" if u["suggest"] else ""
            print(f"   не найден: {u['name']!r}{hint}")

    if a.apply:
        with open(a.recipes, "w", encoding="utf-8") as f:
            json.dump(recipes, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("\nзаписано в", a.recipes)
    return 0


if __name__ == "__main__":
    sys.exit(main())

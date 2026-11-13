#!/usr/bin/env python3
"""Расчёт КБЖУ блюда из пищевой ценности продуктов. Только Б/Ж/У и калории.

## Почему это просто

Вся тяжесть USDA-системы (таблицы nutrient retention factors) существует ради
витаминов и минералов: они разрушаются от нагрева и вымываются в воду, и для
каждой пары «нутриент × способ готовки» нужен свой коэффициент. Для белка и
углеводов коэффициент удержания равен единице — при готовке уходит ВОДА, а не
нутриент. Убрав минералы из области интереса, мы убрали и всю эту машинерию.

Остаётся ровно один член, требующий суждения, — жир:
    Б = Σ белков          У = Σ углеводов
    Ж = Σ жиров − слито + впитано
    ккал = Σ (ккал этикетки продукта × его масса); нет этикетки — 4·Б + 9·Ж + 4·У

Калории берутся с этикетки, а не пересчитываются Этуотером, по двум причинам:
4/9/4 считает усвояемой всю клетчатку (на овощах и специях промах 20–30%) и не
видит спирта, а главное — страница `tools/food.html` считает так же, и два
источника одного числа обязаны совпадать. Подробности — `product_kcal_100g`.

## Ловушка, в которую попадают все

Не нужно знать вес готового блюда. Соблазн велик: «мясо ужарилось, значит надо
пересчитать» — но пересчитывать нечего. Ушла вода, макросы остались. Вес нужен
ТОЛЬКО чтобы дать значения «на 100 г»; для «на порцию» достаточно поделить
сумму на число порций.

## Чего этот модуль НЕ делает

Не берёт данные из USDA. Для российских продуктов этикетка точнее сверки по
названию: «творог 5%» из Вкусвилла и USDA cottage cheese — разные продукты.
Источник каждой записи хранится в `nutrition_100g.source`.

Только stdlib.
"""
import json
import sys

# Коэффициенты Этуотера: сколько килокалорий даёт грамм нутриента.
KCAL_P, KCAL_F, KCAL_C = 4.0, 9.0, 4.0

def to_grams(qty, unit, prod=None):
    """→ масса в граммах или None, если пересчитать нельзя.

    Единица — семьёй (зеркало gramsOf в food.html):
      • г/кг — масса напрямую;
      • мл/л — объём → вес по плотности продукта `g_per_100ml` (г в 100 мл).
        Нет плотности → мл ≈ г (плотность 1): для воды/молока верно, для масла
        (~0.92) ошибка ~8% — в пределах разброса этикеток. Это безопасный откат,
        а НЕ глобальная таблица плотностей (та была бы источником тихого вранья):
        цифра лежит у КОНКРЕТНОГО продукта.
      • шт — только если задан `piece_g` (средний вес штуки). Без него «3 яйца»
        в вес перевести неоткуда — честнее вернуть None и назвать пропуск, чем
        подставить выдуманный вес.
      • стакан/ложка и прочее — None (в вес не переводим; в рецепте они живут
        как показ, а STD-количество вводят граммами/мл/шт).
    """
    if qty is None:
        return None
    u = (unit or "").lower()
    if u == "г":
        return qty
    if u == "кг":
        return qty * 1000.0
    d = (prod or {}).get("g_per_100ml")
    if u == "мл":
        return qty * d / 100.0 if d else qty
    if u == "л":
        return qty * 10.0 * d if d else qty * 1000.0
    if u == "шт" and prod and prod.get("piece_g"):
        return qty * prod["piece_g"]
    return None


def sum_macros(ingredients, products_by_id):
    """Сумма сырых макросов рецепта.

    → (totals, covered, skipped). `covered` — доля учтённой массы: без неё
    результат невозможно интерпретировать, потому что непокрытый продукт
    молча занижает итог. `skipped` объясняет каждый пропуск поимённо.
    """
    tot = {"protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0, "kcal": 0.0}
    mass_known = mass_all = 0.0
    skipped = []

    for g in ingredients:
        p = products_by_id.get(g.get("product_id"))
        grams = to_grams(g.get("qty"), g.get("unit"), p)
        name = g.get("name") or "?"
        if grams is None:
            skipped.append({"name": name, "why": "нет числового количества в граммах"})
            continue
        mass_all += grams

        n1 = (p or {}).get("nutrition_100g")
        if not n1:
            skipped.append({"name": name, "why": "у продукта не заполнена пищевая ценность"})
            continue

        # Варёный вес в рецепте → в сухой: пищевая ценность на этикетке
        # относится к сухому продукту, а в рецепте может стоять готовый вес.
        raw = grams
        if g.get("state") == "cooked" and p.get("cooked_ratio"):
            raw = grams / p["cooked_ratio"]

        for k in ("protein_g", "fat_g", "carb_g"):
            v = n1.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tot[k] += v * raw / 100.0
        kc = product_kcal_100g(n1)
        if kc is not None:
            tot["kcal"] += kc * raw / 100.0
        mass_known += grams

    covered = (mass_known / mass_all) if mass_all else 0.0
    return tot, covered, skipped


def kcal_from(macros):
    return KCAL_P * macros["protein_g"] + KCAL_F * macros["fat_g"] + KCAL_C * macros["carb_g"]


def product_kcal_100g(n1):
    """ккал/100 г продукта: ЭТИКЕТКА приоритетнее, Этуотер — только запасной путь.

    Этуотер (4/9/4) считает всякий углевод усвояемым, а на этикетке в углеводы
    попадает и клетчатка; на овощах и специях расхождение доходит до 25–30%
    (шпинат 23 против 30, лавровый лист 313 против 402), а у вина 4/9/4 не видит
    спирт вовсе (66 против 3). Этикетка ближе к правде, поэтому она и берётся.

    Второе, зачем это здесь: страница и этот модуль обязаны давать ОДНО число.
    Раньше страница суммировала этикетку, а модуль пересчитывал 4/9/4, и на
    реальных рецептах они расходились до 21% («Гуляш из говядины с картофелем» —
    361 против 436 ккал на порцию). Правило одно на обе стороны, зеркальность
    проверяется тестом контракта страниц.
    """
    if not n1:
        return None
    k = n1.get("kcal")
    if isinstance(k, (int, float)) and not isinstance(k, bool):
        return float(k)
    macros = {}
    for key in ("protein_g", "fat_g", "carb_g"):
        v = n1.get(key)
        macros[key] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
    return kcal_from(macros) if any(macros.values()) else None


def dish_nutrition(recipe, products, fat_drained_g=0.0, fat_absorbed_g=0.0):
    """КБЖУ одной порции.

    fat_drained_g  — жир, слитый со сковороды (жарка фарша, мяса).
    fat_absorbed_g — часть налитого масла, реально впитавшаяся в блюдо.
                     Масло уже посчитано в ингредиентах целиком, поэтому
                     непоглощённый остаток вычитается: передавайте сюда
                     ВПИТАВШЕЕСЯ, а функция вычтет разницу сама через
                     fat_drained_g. Проще всего измерить взвешиванием бутылки
                     до и после — один раз, чтобы откалибровать свою привычку.
    """
    by_id = {p["id"]: p for p in products if p.get("id")}
    tot, covered, skipped = sum_macros(recipe.get("ingredients") or [], by_id)

    tot = dict(tot)
    fat_before = tot["fat_g"]
    tot["fat_g"] = max(0.0, fat_before - fat_drained_g + fat_absorbed_g)
    # Калории накоплены по этикеткам (product_kcal_100g), поэтому правку жира
    # надо провести и по ним — иначе слитый жир уменьшал бы Ж, а ккал стояли бы.
    tot["kcal"] = max(0.0, tot["kcal"] + KCAL_F * (tot["fat_g"] - fat_before))

    servings = recipe.get("servings") or 1
    per = {k: round(v / servings, 1) for k, v in tot.items()}
    per["kcal"] = round(tot["kcal"] / servings)

    out = {"per_portion": per, "total": tot, "servings": servings,
           "covered": round(covered, 3), "skipped": skipped,
           "per_100g": None, "portion_g": None}

    # Значения «на 100 г» требуют массы ГОТОВОГО блюда — единственной величины,
    # которую нельзя вывести из данных. Она зависит от того, сколько выпарилось
    # воды, а это функция посуды, крышки, огня и времени; у одного и того же
    # рецепта на разных плитах разница бывает двукратной. Поэтому массу не
    # оцениваем, а берём измеренную: поставить готовое блюдо на весы — пять
    # секунд и точное число. Нет числа — нет и значений на 100 г, врать не будем.
    fin = recipe.get("finished_g")
    if isinstance(fin, (int, float)) and not isinstance(fin, bool) and fin > 0:
        k = 100.0 / fin
        out["per_100g"] = {kk: round(vv * k, 1) for kk, vv in tot.items()}
        out["per_100g"]["kcal"] = round(tot["kcal"] * k)
        out["portion_g"] = round(fin / servings)
    return out


def compare(stated, computed, tol_low=30, tol_high=5):
    """Сверка заявленного КБЖУ с расчётом. Проверка НАМЕРЕННО односторонняя.

    Заявленное ВЫШЕ расчёта — почти наверняка ошибка: жиру взяться неоткуда,
    добавленное масло уже сидит в ингредиентах. Порог узкий (5%).

    Заявленное НИЖЕ — норма: столько уходит со слитым жиром и невпитавшимся
    маслом. Порог широкий (30%), потому что «слил избыток» никто не меряет.
    """
    if not stated or stated.get("kcal") is None or not computed:
        return None
    c = computed["per_portion"]["kcal"]
    if not c:
        return None
    dev = (stated["kcal"] - c) / c * 100
    if dev > tol_high:
        return {"severity": "warning", "dev_pct": round(dev),
                "message": f"заявлено {stated['kcal']:g} ккал, а по ингредиентам выходит {c} "
                           f"(+{dev:.0f}%) — выше суммы продуктов взяться неоткуда, "
                           f"проверьте числа или состав"}
    if dev < -tol_low:
        return {"severity": "warning", "dev_pct": round(dev),
                "message": f"заявлено {stated['kcal']:g} ккал против {c} по ингредиентам "
                           f"({dev:.0f}%) — слишком большая недостача даже с учётом слитого жира"}
    return {"severity": "ok", "dev_pct": round(dev),
            "message": f"сходится: заявлено {stated['kcal']:g}, по ингредиентам {c} ({dev:+.0f}%)"}


def main():
    """CLI: посчитать КБЖУ всех рецептов, у которых хватает данных."""
    import argparse
    ap = argparse.ArgumentParser(description="Расчёт КБЖУ блюда по продуктам")
    ap.add_argument("--recipes", required=True)
    ap.add_argument("--products", required=True)
    ap.add_argument("--min-covered", type=float, default=0.8,
                    help="не считать, если покрыто меньше этой доли массы (0..1)")
    a = ap.parse_args()

    recipes = json.load(open(a.recipes, encoding="utf-8"))["recipes"]
    products = json.load(open(a.products, encoding="utf-8"))["products"]

    shown = 0
    for r in recipes:
        res = dish_nutrition(r, products)
        if res["covered"] < a.min_covered:
            continue
        shown += 1
        per = res["per_portion"]
        line = f"{r['title'][:40]:40} {per['kcal']:>5} ккал · Б {per['protein_g']:>5} " \
               f"Ж {per['fat_g']:>5} У {per['carb_g']:>5}  (покрыто {res['covered']*100:.0f}%)"
        cmp_ = compare(r.get("nutrition"), res)
        if cmp_:
            line += "  " + ("✓" if cmp_["severity"] == "ok" else "⚠") + f" {cmp_['dev_pct']:+d}%"
        print(line)
    if not shown:
        print(f"Ни одного рецепта с покрытием ≥ {a.min_covered*100:.0f}%: "
              f"заполните nutrition_100g у продуктов (начните с самых массовых).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

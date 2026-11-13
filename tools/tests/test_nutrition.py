#!/usr/bin/env python3
"""Тесты расчёта КБЖУ блюда (tools/food/nutrition.py).

Ключевые свойства, которые тест обязан держать:
  * макросы СОХРАНЯЮТСЯ — уходит вода, а не белок; никаких коэффициентов
    удержания для Б и У;
  * вес готового блюда в расчёте «на порцию» не участвует вообще;
  * непокрытые продукты не занижают итог молча — считается доля покрытия;
  * сверка с заявленным КБЖУ односторонняя: выше суммы продуктов — ошибка,
    ниже — норма (слитый жир).

Запуск:
    python3 tools/tests/test_nutrition.py
Только stdlib.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/food"))

import nutrition as nt  # noqa: E402

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
    {"id": "kefir", "name": "Кефир 2,5%",
     "nutrition_100g": {"kcal": 53, "protein_g": 2.9, "fat_g": 2.5, "carb_g": 4.0}},
    {"id": "muka", "name": "Мука",
     "nutrition_100g": {"kcal": 342, "protein_g": 10.3, "fat_g": 1.1, "carb_g": 70.6}},
    {"id": "maslo", "name": "Масло подсолнечное",
     "nutrition_100g": {"kcal": 899, "protein_g": 0, "fat_g": 99.9, "carb_g": 0}},
    {"id": "grechka", "name": "Гречка", "cooked_ratio": 2.5,
     "nutrition_100g": {"kcal": 308, "protein_g": 12.6, "fat_g": 3.3, "carb_g": 57.1}},
    {"id": "yaico", "name": "Яйца", "unit": "шт", "piece_g": 55,
     "nutrition_100g": {"kcal": 157, "protein_g": 12.7, "fat_g": 11.5, "carb_g": 0.7}},
    {"id": "sol", "name": "Соль"},                       # без пищевой ценности
]
BY_ID = {p["id"]: p for p in PRODUCTS}

# ── to_grams ────────────────────────────────────────────────────────────────
print("to_grams")
check("граммы", nt.to_grams(500, "г") == 500)
check("килограммы", nt.to_grams(1.5, "кг") == 1500)
# Без плотности продукта мл≈г (безопасный откат): для воды/молока верно, для
# масла ~8% — ниже разброса этикеток. Глобальной таблицы плотностей нет.
check("миллилитры без плотности считаем граммами", nt.to_grams(500, "мл") == 500)
check("литры без плотности", nt.to_grams(2, "л") == 2000)
# С плотностью продукта (г в 100 мл) объём переводится точно — цифра у КОНКРЕТНОГО
# продукта, а не в общей таблице. Масло 92 г/100 мл: 30 мл → 27.6 г (было бы 30).
check("мл с плотностью продукта: 30 мл × 92/100 = 27.6",
      abs(nt.to_grams(30, "мл", {"g_per_100ml": 92}) - 27.6) < 1e-9)
check("л с плотностью: 1 л молока × 10 × 103 = 1030 г",
      abs(nt.to_grams(1, "л", {"g_per_100ml": 103}) - 1030) < 1e-9)
check("плотность не трогает весовые единицы",
      nt.to_grams(500, "г", {"g_per_100ml": 92}) == 500)
check("штуки без веса штуки перевести нельзя", nt.to_grams(2, "шт") is None)
# С piece_g штуки становятся граммами: «2 яйца × 55 г = 110 г».
check("штуки с piece_g переводятся в граммы",
      nt.to_grams(2, "шт", {"piece_g": 55}) == 110)
check("штуки без piece_g остаются непереводимыми",
      nt.to_grams(2, "шт", {"piece_g": None}) is None)
check("piece_g не трогает весовые единицы",
      nt.to_grams(500, "г", {"piece_g": 55}) == 500)
check("«по вкусу» нельзя перевести", nt.to_grams(None, None) is None)
check("незнакомая единица", nt.to_grams(1, "пучок") is None)

# ── sum_macros ──────────────────────────────────────────────────────────────
print("sum_macros")
tot, cov, skip = nt.sum_macros(
    [{"name": "Мука", "product_id": "muka", "qty": 100, "unit": "г"}], BY_ID)
check("100 г продукта = значения этикетки", round(tot["protein_g"], 2) == 10.3)
check("покрытие 100%", cov == 1.0)
check("ничего не пропущено", skip == [])

tot, cov, skip = nt.sum_macros(
    [{"name": "Мука", "product_id": "muka", "qty": 200, "unit": "г"}], BY_ID)
check("масса масштабируется линейно", round(tot["carb_g"], 1) == round(70.6 * 2, 1))

# Непокрытый продукт обязан быть ВИДЕН: молчаливое занижение итога хуже отказа.
tot, cov, skip = nt.sum_macros([
    {"name": "Мука", "product_id": "muka", "qty": 100, "unit": "г"},
    {"name": "Соль", "product_id": "sol", "qty": 100, "unit": "г"},
], BY_ID)
check("непокрытый продукт снижает долю покрытия", cov == 0.5)
check("непокрытый продукт назван поимённо", len(skip) == 1 and skip[0]["name"] == "Соль")
check("причина пропуска объяснена", "пищевая ценность" in skip[0]["why"])

tot, cov, skip = nt.sum_macros([
    {"name": "Соль", "product_id": "sol", "qty": None, "unit": None}], BY_ID)
check("«по вкусу» не ломает расчёт", tot["protein_g"] == 0)
check("«по вкусу» объяснено отдельно", "количеств" in skip[0]["why"])

# Варёный вес → сухой: этикетка описывает сухую крупу.
tot, _, _ = nt.sum_macros(
    [{"name": "Гречка", "product_id": "grechka", "qty": 250, "unit": "г", "state": "cooked"}], BY_ID)
check("варёный вес пересчитан в сухой (250/2.5 = 100 г)", round(tot["protein_g"], 1) == 12.6)
tot_dry, _, _ = nt.sum_macros(
    [{"name": "Гречка", "product_id": "grechka", "qty": 100, "unit": "г"}], BY_ID)
check("сухой вес совпал с пересчитанным варёным",
      round(tot["protein_g"], 2) == round(tot_dry["protein_g"], 2))

# Штучный ингредиент теперь входит в подсчёт: 2 яйца × 55 г = 110 г,
# белок = 12.7 × 110/100 = 13.97. Без piece_g он молча выпал бы.
tot, cov, skip = nt.sum_macros(
    [{"name": "Яйца", "product_id": "yaico", "qty": 2, "unit": "шт"}], BY_ID)
check("2 яйца учтены по весу штуки", round(tot["protein_g"], 2) == round(12.7 * 1.10, 2))
check("штучный ингредиент с piece_g не пропущен", skip == [])

# ── dish_nutrition ──────────────────────────────────────────────────────────
print("dish_nutrition")
OLADI = {"id": "o", "title": "Оладушки", "servings": 5, "ingredients": [
    {"name": "Кефир", "product_id": "kefir", "qty": 500, "unit": "мл"},
    {"name": "Мука", "product_id": "muka", "qty": 300, "unit": "г"},
    {"name": "Масло", "product_id": "maslo", "qty": 50, "unit": "мл"},
]}
res = nt.dish_nutrition(OLADI, PRODUCTS)
check("покрытие 100%", res["covered"] == 1.0)
check("порций сохранено", res["servings"] == 5)
check("порция = итог / порции",
      abs(res["per_portion"]["protein_g"] - res["total"]["protein_g"] / 5) < 0.05)

# ГЛАВНОЕ СВОЙСТВО: вес готового блюда нигде не нужен. Удвоение порций при том
# же составе делит на порции — и только; никакого «а сколько воды выпарилось».
res10 = nt.dish_nutrition(dict(OLADI, servings=10), PRODUCTS)
check("вдвое больше порций — вдвое меньше на порцию",
      abs(res10["per_portion"]["kcal"] * 2 - res["per_portion"]["kcal"]) <= 1)
check("итог блюда от числа порций не зависит",
      abs(res10["total"]["fat_g"] - res["total"]["fat_g"]) < 0.01)

# Жир — единственный член, который двигается способом готовки.
drained = nt.dish_nutrition(OLADI, PRODUCTS, fat_drained_g=20)
check("слитый жир уменьшает жиры",
      round(res["total"]["fat_g"] - drained["total"]["fat_g"], 1) == 20.0)
check("слитый жир уменьшает калории", drained["per_portion"]["kcal"] < res["per_portion"]["kcal"])
check("белки и углеводы слив жира НЕ трогает",
      drained["total"]["protein_g"] == res["total"]["protein_g"] and
      drained["total"]["carb_g"] == res["total"]["carb_g"])
check("жир не уходит в минус при абсурдном сливе",
      nt.dish_nutrition(OLADI, PRODUCTS, fat_drained_g=9999)["total"]["fat_g"] == 0)
absorbed = nt.dish_nutrition(OLADI, PRODUCTS, fat_absorbed_g=10)
check("впитанное масло увеличивает жиры",
      round(absorbed["total"]["fat_g"] - res["total"]["fat_g"], 1) == 10.0)

# Калории берутся с ЭТИКЕТКИ продукта, Этуотер — только когда её нет. Причина не
# академическая: страница food.html считает так же, и раньше два источника одного
# числа расходились до 21% на реальных рецептах («Гуляш из говядины с картофелем»
# — 361 против 436 ккал на порцию). Плюс 4/9/4 считает усвояемой всю клетчатку.
lbl_total = sum(
    (BY_ID[i["product_id"]]["nutrition_100g"]["kcal"]
     * nt.to_grams(i["qty"], i["unit"], BY_ID[i["product_id"]]) / 100.0)
    for i in OLADI["ingredients"])
check("ккал — сумма этикеток, а не пересчёт 4/9/4",
      abs(res["per_portion"]["kcal"] - round(lbl_total / 5)) <= 1)
check("этикетка и Этуотер на этих продуктах РАЗНЫЕ (тест не тавтология)",
      abs(nt.kcal_from(res["total"]) - lbl_total) > 5)
check("этикетка приоритетнее Этуотера",
      nt.product_kcal_100g({"kcal": 66, "protein_g": 0.1, "fat_g": 0, "carb_g": 0.6}) == 66)
# Вино: 4/9/4 не видит спирта (3 ккал против 66 на этикетке) — вот цена пересчёта.
check("без этикетки — Этуотер по макросам",
      nt.product_kcal_100g({"protein_g": 10, "fat_g": 1, "carb_g": 70}) == 4 * 10 + 9 + 4 * 70)
check("пусто — ни числа, ни выдумки",
      nt.product_kcal_100g(None) is None and nt.product_kcal_100g({}) is None)
# Правка жира обязана двигать и калории: иначе слитый жир уменьшал бы Ж, а ккал
# стояли бы на месте — молчаливое расхождение внутри одной карточки.
check("слив жира уменьшает ккал ровно на 9 ккал/г",
      abs((res["total"]["kcal"] - drained["total"]["kcal"]) - 9 * 20) < 0.01)
check("впитанное масло увеличивает ккал ровно на 9 ккал/г",
      abs((absorbed["total"]["kcal"] - res["total"]["kcal"]) - 9 * 10) < 0.01)

# ── «на 100 г»: единственное место, где нужна масса готового блюда ──────────
print("на 100 г")
check("без измеренной массы значений на 100 г НЕТ (не выдумываем)",
      res["per_100g"] is None and res["portion_g"] is None)

# Сырая масса оладушек 850 г, готовых — 700 г: 150 г воды выпарилось.
# Именно этот испарённый остаток и невозможно предсказать, поэтому его меряют.
withw = nt.dish_nutrition(dict(OLADI, finished_g=700), PRODUCTS)
check("с измеренной массой значения на 100 г появляются", withw["per_100g"] is not None)
check("вес порции = масса / порции", withw["portion_g"] == 140)
check("на 100 г = итог × 100 / масса",
      abs(withw["per_100g"]["protein_g"] - withw["total"]["protein_g"] * 100 / 700) < 0.1)

# Ключевое: испарение НЕ меняет ни итог блюда, ни значения на порцию —
# только концентрацию на 100 г. Это и есть причина, по которой «на порцию»
# считается без массы, а «на 100 г» — нет.
dry = nt.dish_nutrition(dict(OLADI, finished_g=500), PRODUCTS)
check("сильнее выпарилось — на порцию НЕ изменилось",
      dry["per_portion"]["kcal"] == withw["per_portion"]["kcal"])
check("сильнее выпарилось — на 100 г выросло",
      dry["per_100g"]["kcal"] > withw["per_100g"]["kcal"])
check("нулевая масса не роняет расчёт",
      nt.dish_nutrition(dict(OLADI, finished_g=0), PRODUCTS)["per_100g"] is None)
check("нечисловая масса игнорируется",
      nt.dish_nutrition(dict(OLADI, finished_g="700"), PRODUCTS)["per_100g"] is None)

# ── compare: проверка НАМЕРЕННО односторонняя ───────────────────────────────
print("compare")
computed = {"per_portion": {"kcal": 400}}
check("совпадение — ок", nt.compare({"kcal": 400}, computed)["severity"] == "ok")
check("на 20% ниже — норма (слитый жир)",
      nt.compare({"kcal": 320}, computed)["severity"] == "ok")
# Заявленное ВЫШЕ суммы продуктов — жиру взяться неоткуда.
check("на 20% выше — предупреждение",
      nt.compare({"kcal": 480}, computed)["severity"] == "warning")
check("сообщение объясняет, почему выше нельзя",
      "взяться неоткуда" in nt.compare({"kcal": 480}, computed)["message"])
# Асимметрия порогов — суть проверки: сверху 5% (жиру взяться неоткуда),
# снизу 30% (слитый жир никто не меряет). Одинаковая на 10% недостача и
# превышение обязаны трактоваться по-разному.
check("−10% — норма, +10% — предупреждение",
      nt.compare({"kcal": 360}, computed)["severity"] == "ok" and
      nt.compare({"kcal": 440}, computed)["severity"] == "warning")
check("ровно на пороге сверху ещё не ругаемся",
      nt.compare({"kcal": 420}, computed)["severity"] == "ok")
check("недостача в 2 раза — тоже подозрительно",
      nt.compare({"kcal": 200}, computed)["severity"] == "warning")
check("без заявленного КБЖУ сверки нет", nt.compare(None, computed) is None)
check("без расчёта сверки нет", nt.compare({"kcal": 400}, None) is None)

print(f"\nnutrition: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

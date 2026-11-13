#!/usr/bin/env python3
"""Тесты валидатора рецептов (tools/food/validate_recipe.py).

Валидатор — эталонная реализация разбора `.md`-рецепта: страница «Еда» будет
зеркалить его JS-парсером, поэтому дрейф с любой стороны должен ронять тест.

Покрыто: parse_qty (граммовки/диапазоны/«по вкусу»), разбор шапки и секций,
два пути получения ингредиентов (```json-блок и markdown-таблица) и их сверка,
blocking-проверки (порции-делитель, qty строкой), warning-проверки удобства
(имя и длительность шага, количества в тексте шага, стоп-лист).

Запуск:
    python3 tools/tests/test_validate_recipe.py
Только stdlib.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/food"))

import validate_recipe as vr  # noqa: E402

passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def sev(issues, s):
    return [i for i in issues if i["severity"] == s]


def cats(issues, s=None):
    return {i["category"] for i in issues if s is None or i["severity"] == s}


# ── эталонный рецепт: то, что должен выдавать проект Claude.ai ───────────────
GOOD = """# Паста Болоньезе

**Кухня:** итальянская (Болонья, Эмилия-Романья)
**Порции:** 3 обеда × 2 человека = 6 порций
**Время:** подготовка 15 мин / приготовление 2 ч 30 мин / итого 2 ч 45 мин
**Сложность:** 2 из 5
**КБЖУ на порцию:** 690 ккал · Б 42 г · Ж 28 г · У 62 г

---

## Ингредиенты

| Ингредиент | На 6 порций |
|---|---|
| Говяжий фарш (80/20) | 600 г |
| Панчетта | 150 г |
| Томатная паста | 80 г |
| Белое вино (сухое) | 150 мл |
| Соль, чёрный перец | по вкусу |

## Приготовление

### Шаг 1. Подготовка овощей (5 мин)
Нарезать панчетту 150 г одинаковыми кубиками ~3 мм.

### Шаг 2. Обжарка фарша (8 мин)
Добавить фарш 600 г, разламывая деревянной ложкой. Жарить на среднем огне 8 мин.

### Шаг 3. Томатная паста и вино (3 мин)
Добавить томатную пасту 80 г, готовить 1 мин. Влить белое вино 150 мл,
деглейзировать кастрюлю, варить 2 мин до полного испарения алкоголя.

## Инвентарь
Кастрюля 3–4 л с толстым дном.

## Хранение
В холодильнике: 4–5 дней в герметичном контейнере.

## Советы по подаче
Подать с тёртым пармезаном.

## Источники
https://example.org/ragu-alla-bolognese

```json
{
  "servings": 6,
  "nutrition": { "kcal": 690, "protein_g": 42, "fat_g": 28, "carb_g": 62 },
  "ingredients": [
    { "name": "Говяжий фарш", "qty": 600, "unit": "г" },
    { "name": "Панчетта", "qty": 150, "unit": "г" },
    { "name": "Томатная паста", "qty": 80, "unit": "г" },
    { "name": "Белое вино", "qty": 150, "unit": "мл" },
    { "name": "Соль, чёрный перец", "qty": null, "unit": null }
  ]
}
```
"""


def variant(**repl):
    """Эталон с точечными заменами — чтобы негативы отличались одной строкой."""
    out = GOOD
    for old, new in repl.items():
        out = out.replace(old.replace("__", " "), new)
    return out


# ── parse_qty ────────────────────────────────────────────────────────────────
print("parse_qty")
check("граммы", vr.parse_qty("600 г") == (600.0, "г"))
check("миллилитры", vr.parse_qty("150 мл") == (150.0, "мл"))
check("штуки", vr.parse_qty("1 шт") == (1.0, "шт"))
check("диапазон → нижняя граница", vr.parse_qty("150–200 г") == (150.0, "г"))
check("диапазон через дефис", vr.parse_qty("4-5 л") == (4.0, "л"))
check("десятичная запятая", vr.parse_qty("2,5 л") == (2.5, "л"))
check("«по вкусу» → без числа", vr.parse_qty("по вкусу") == (None, None))
check("«по желанию» → без числа", vr.parse_qty("по желанию") == (None, None))
check("«щепотка» → без числа", vr.parse_qty("щепотка") == (None, None))
check("хвост в скобках не мешает", vr.parse_qty("1 шт (опционально)") == (1.0, "шт"))
check("пустая строка", vr.parse_qty("") == (None, None))
check("None", vr.parse_qty(None) == (None, None))

print("clean_name")
check("скобочное уточнение срезается", vr.clean_name("Говяжий фарш (80/20)") == "Говяжий фарш")
check("без скобок не меняется", vr.clean_name("Панчетта") == "Панчетта")
check("хвостовая запятая срезается", vr.clean_name("Морковь, ") == "Морковь")

# ── разбор эталона ───────────────────────────────────────────────────────────
print("эталонный рецепт")
recipe, issues = vr.validate(GOOD)
check("название", recipe["title"] == "Паста Болоньезе")
check("кухня из шапки", recipe["cuisine"].startswith("итальянская"))
check("порции из json-блока", recipe["servings"] == 6)
check("формулировка порций сохранена", "3 обеда" in recipe["servings_note"])
check("сложность числом", recipe["difficulty"] == 2)
check("КБЖУ разобрано", recipe["nutrition"]["kcal"] == 690)
check("ингредиентов 5", len(recipe["ingredients"]) == 5)
check("шагов 3", len(recipe["steps"]) == 3)
check("«по вкусу» → qty None",
      [g for g in recipe["ingredients"] if g["name"].startswith("Соль")][0]["qty"] is None)
check("секция хранения подхвачена", recipe["storage"].startswith("В холодильнике"))
check("секция источников подхвачена", "example.org" in recipe["sources"])
check("эталон без blocking", not sev(issues, "blocking"))
check("эталон без замечаний про inline-количества", "inline_qty" not in cats(issues))
check("эталон без замечаний про шаги", "steps" not in cats(issues, "warning"))

# ── пассивный шаг «без участия» (.md-мостик, зеркало _PASSIVE_MD страницы) ──
_pas_md = ("# Тест\n**Порции:** 2\n\n## Ингредиенты\n- Мука — 100 г\n\n"
           "## Приготовление\n### Шаг 1. Замес (5 мин)\nЗамесить муку 100 г.\n"
           "### Шаг 2. Охлаждение (30 мин, без участия)\nУбрать в холодильник.\n")
_pr, _pi, _ps = vr.parse_recipe(_pas_md)
check("пассивный шаг помечен passive=True", _pr["steps"][1].get("passive") is True)
check("активный шаг без passive", "passive" not in _pr["steps"][0])
check("ключевое слово вырезано из подписи, длительность цела",
      "без участия" not in _pr["steps"][1]["title"] and "30 мин" in _pr["steps"][1]["title"])

# ── measure ингредиента: показ («1 стакан»), в расчёт идёт qty ──────────────
_meas_ok = ('# Тест\n**Порции:** 2\n\n## Ингредиенты\n- Рис\n\n## Приготовление\n'
            '### Шаг 1. Варка (10 мин)\nОтварить рис 180 г.\n\n```json\n'
            '{"schema":"food-recipe@1","title":"Т","servings":2,'
            '"ingredients":[{"name":"Рис","qty":180,"unit":"г","measure":"1 стакан"}],'
            '"steps":[{"title":"Шаг 1. Варка (10 мин)","text":"Отварить рис 180 г."}]}\n```\n')
_mr, _mi = vr.validate(_meas_ok)
check("measure строкой доходит до рецепта", _mr["ingredients"][0].get("measure") == "1 стакан")
check("measure строкой не блокирует", not sev(_mi, "blocking"))
_, _min = vr.validate(_meas_ok.replace('"measure":"1 стакан"', '"measure":1'))
check("measure числом блокирует (это показ, число — в qty)",
      "ingredients" in cats(_min, "blocking"))

# ── blocking ─────────────────────────────────────────────────────────────────
print("blocking")
_, i0 = vr.validate(variant(**{'"servings": 6': '"servings": 0'}))
check("servings=0 блокирует", "servings" in cats(i0, "blocking"))

_, ineg = vr.validate(variant(**{'"servings": 6': '"servings": -2'}))
check("servings отрицательный блокирует", "servings" in cats(ineg, "blocking"))

_, istr = vr.validate(variant(**{'"servings": 6': '"servings": "6"'}))
check("servings строкой блокирует", "servings" in cats(istr, "blocking"))

# «600»+«400» при суммировании склеится в «600400» — тихо и катастрофично
_, iq = vr.validate(variant(**{'"qty": 600': '"qty": "600"'}))
check("qty строкой блокирует", "ingredients" in cats(iq, "blocking"))
check("сообщение про склейку понятное",
      any("склеится" in i["message"] for i in sev(iq, "blocking")))

_, ib = vr.validate(variant(**{'"qty": 600': '"qty": true'}))
check("qty булево блокирует", "ingredients" in cats(ib, "blocking"))

broken_json = GOOD.replace('"servings": 6,', '"servings": 6')
_, ij = vr.validate(broken_json)
check("битый json-блок блокирует", "json_block" in cats(ij, "blocking"))

# json-блок и таблица разъехались → закупка и готовка будут врать по-разному
dropped = GOOD.replace('    { "name": "Панчетта", "qty": 150, "unit": "г" },\n', "")
_, im = vr.validate(dropped)
check("расхождение блока и таблицы блокирует", "ingredients" in cats(im, "blocking"))
check("сообщение называет обе стороны",
      any("таблица" in i["message"] for i in sev(im, "blocking")))

no_title = GOOD.replace("# Паста Болоньезе", "Паста Болоньезе")
_, it = vr.validate(no_title)
check("нет заголовка → blocking", "title" in cats(it, "blocking"))

no_steps = GOOD.split("## Приготовление")[0] + "## Инвентарь\nКастрюля.\n"
_, istep = vr.validate(no_steps)
check("нет шагов → blocking", "steps" in cats(istep, "blocking"))

# ── запасной путь: markdown без json-блока ───────────────────────────────────
print("markdown-фолбэк")
md_only = GOOD[:GOOD.index("```json")]
r_md, i_md = vr.validate(md_only)
check("без json-блока разбирается", not sev(i_md, "blocking"))
check("фолбэк предупреждает о себе", "json_block" in cats(i_md, "warning"))
check("ингредиентов столько же", len(r_md["ingredients"]) == len(recipe["ingredients"]))
check("количества те же", [g["qty"] for g in r_md["ingredients"]] ==
      [g["qty"] for g in recipe["ingredients"]])
check("единицы те же", [g["unit"] for g in r_md["ingredients"]] ==
      [g["unit"] for g in recipe["ingredients"]])
check("имена очищены от скобок", r_md["ingredients"][0]["name"] == "Говяжий фарш")
check("порции взяты из шапки", r_md["servings"] == 6)
check("шаги те же", len(r_md["steps"]) == len(recipe["steps"]))

# ── warning: удобство на кухне ───────────────────────────────────────────────
print("warning")
# Ровно дефект, найденный в реальном PDF: в таблице 80 г, в шаге — «томатную пасту»
no_inline = GOOD.replace("Добавить томатную пасту 80 г", "Добавить томатную пасту")
_, iw = vr.validate(no_inline)
check("количество не в тексте шага → warning", "inline_qty" in cats(iw, "warning"))
check("сообщение называет продукт",
      any("Томатная паста" in i["message"] for i in sev(iw, "warning")))
check("это не blocking (рецепт остаётся рабочим)", not sev(iw, "blocking"))

# РЕАЛЬНЫЙ ДЕФЕКТ, найденный на живых данных 2026-07-20. Текст последнего шага
# вбирал в себя всё до конца файла — включая машиночитаемый ```json-хвост. А в
# хвосте по определению лежат ВСЕ количества, поэтому проверка «количество
# продублировано в тексте шага» находила число всегда и молча проходила.
# Молчащая проверка хуже отсутствующей: 21 рецепт числился «в порядке».
# Проявлялось только когда после шагов не следовало ни одного `## `-раздела.
bare = """# Тест

**Порции:** 2
**КБЖУ на порцию:** 300 ккал · Б 20 г · Ж 10 г · У 30 г

## Ингредиенты

| Ингредиент | На 2 порций |
|---|---|
| Курица | 250 г |

## Приготовление

### Шаг 1. Обжарка (5 мин)
Курицу обжарить до готовности.

```json
{"servings": 2, "ingredients": [{"name": "Курица", "qty": 250, "unit": "г"}]}
```
"""
_rb, ib = vr.validate(bare)
check("json-хвост не считается текстом шага (проверка не молчит)",
      "inline_qty" in cats(ib, "warning"))
check("текст последнего шага обрывается на ```",
      "json" not in vr.parse_recipe(bare)[2][0]["text"])
# Обратная сторона: обрыв не должен съедать сам текст шага.
check("текст шага до ``` сохранён целиком",
      vr.parse_recipe(bare)[2][0]["text"] == "Курицу обжарить до готовности.")

no_name = GOOD.replace("### Шаг 2. Обжарка фарша (8 мин)", "### Шаг 2 (8 мин)")
_, inm = vr.validate(no_name)
check("шаг без имени → warning", any("оглавление" in i["message"] for i in sev(inm, "warning")))

no_dur = GOOD.replace("### Шаг 2. Обжарка фарша (8 мин)", "### Шаг 2. Обжарка фарша")
_, idur = vr.validate(no_dur)
check("шаг без длительности → warning", any("⏱" in i["message"] for i in sev(idur, "warning")))

long_step = GOOD.replace("Жарить на среднем огне 8 мин.",
                         "Жарить на среднем огне 8 мин. " + "Ещё действие. " * 60)
_, ilong = vr.validate(long_step)
check("слишком длинный шаг → warning", any("не атомарен" in i["message"]
                                           for i in sev(ilong, "warning")))

no_kbju = GOOD.replace('"nutrition": { "kcal": 690, "protein_g": 42, "fat_g": 28, '
                       '"carb_g": 62 },\n  ', "")
_, ik = vr.validate(no_kbju)
check("нет КБЖУ → warning", "nutrition" in cats(ik, "warning"))
check("нет КБЖУ — не blocking", not sev(ik, "blocking"))

# ── КБЖУ: единственная проверка, возможная без базы нутриентов ──────────────
# Она НЕ подтверждает, что числа верны для блюда (КБЖУ блюда — не сумма сырых
# ингредиентов: сливается жир, впитывается масло, выпаривается алкоголь), а
# только что заявленные четыре числа не противоречат друг другу.
print("КБЖУ")
check("эталон сходится по Этуотеру", "nutrition" not in cats(issues, "warning"))
check("прямой вызов на согласованных числах молчит",
      vr.check_atwater({"kcal": 690, "protein_g": 42, "fat_g": 28, "carb_g": 62}) == [])
# 690 против 4·42+9·28+4·62 = 668 → −3%, в допуске
_bad = vr.check_atwater({"kcal": 300, "protein_g": 42, "fat_g": 28, "carb_g": 62})
check("завышенные ккал ловятся", len(_bad) == 1)
check("сообщение называет обе величины",
      _bad and "668" in _bad[0]["message"] and "300" in _bad[0]["message"])
check("подсказка про частую причину", _bad and "перепутанные" in _bad[0]["message"])
# Перепутанные местами Б и Ж — реальный класс опечатки
check("перепутанные Б и Ж ловятся",
      len(vr.check_atwater({"kcal": 690, "protein_g": 28, "fat_g": 62, "carb_g": 42})) == 1)
check("опечатка в разряде ловится",
      len(vr.check_atwater({"kcal": 6900, "protein_g": 42, "fat_g": 28, "carb_g": 62})) == 1)
# Неполные данные не должны порождать ложную тревогу
check("без ккал молчит", vr.check_atwater({"protein_g": 42}) == [])
check("без Б/Ж/У молчит", vr.check_atwater({"kcal": 690}) == [])
check("нечисловые значения молчат",
      vr.check_atwater({"kcal": 690, "protein_g": "42", "fat_g": 28, "carb_g": 62}) == [])
_no_nu = GOOD.replace('"nutrition": { "kcal": 690, "protein_g": 42, "fat_g": 28, '
                      '"carb_g": 62 },\n  ', "")
check("отсутствие КБЖУ — по-прежнему warning, а не ошибка сверки",
      "nutrition" in cats(vr.validate(_no_nu)[1], "warning"))

no_src = GOOD.replace("## Источники\nhttps://example.org/ragu-alla-bolognese", "")
_, isr = vr.validate(no_src)
check("нет источников → warning", "sources" in cats(isr, "warning"))

# Варёный вес без пометки → в список уедет в 2,5–3 раза больше нужного.
GRAIN = GOOD.replace('    { "name": "Панчетта", "qty": 150, "unit": "г" },',
                     '    { "name": "Гречка варёная", "qty": 390, "unit": "г" },') \
            .replace("| Панчетта | 150 г |", "| Гречка варёная | 390 г |") \
            .replace("Нарезать панчетту 150 г одинаковыми кубиками ~3 мм.",
                     "Отварить гречку 390 г заранее.")
_, ig = vr.validate(GRAIN)
check("варёный вес без state → warning", "cooked_state" in cats(ig, "warning"))
check("предупреждение называет продукт",
      any("Гречка варёная" in i["message"] for i in sev(ig, "warning")))
check("варёный вес без state — не blocking", not sev(ig, "blocking"))

GRAIN_OK = GRAIN.replace('{ "name": "Гречка варёная", "qty": 390, "unit": "г" }',
                         '{ "name": "Гречка варёная", "qty": 390, "unit": "г", "state": "cooked" }')
r_ok, i_ok = vr.validate(GRAIN_OK)
check("с пометкой state=cooked предупреждения нет", "cooked_state" not in cats(i_ok, "warning"))
check("state доехал до разобранного рецепта",
      [g for g in r_ok["ingredients"] if g["name"].startswith("Гречка")][0]["state"] == "cooked")

GRAIN_TYPO = GRAIN.replace('{ "name": "Гречка варёная", "qty": 390, "unit": "г" }',
                           '{ "name": "Гречка варёная", "qty": 390, "unit": "г", "state": "cookd" }')
_, i_typo = vr.validate(GRAIN_TYPO)
check("опечатка в state → blocking", "ingredients" in cats(i_typo, "blocking"))

# Стоп-лист — это вкус, а не структура: предупреждаем, но не блокируем.
with_stop = GOOD.replace("| Панчетта | 150 г |", "| Шампиньоны | 150 г |")
_, ist = vr.validate(with_stop)
check("стоп-лист → warning", "stop_list" in cats(ist, "warning"))
check("стоп-лист называет категорию", any("грибы" in i["message"] for i in sev(ist, "warning")))
check("стоп-лист НЕ блокирует", not sev(ist, "blocking"))

# ── CLI ──────────────────────────────────────────────────────────────────────
print("cli")
import json as _json  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "Паста_Болоньезе.md"
    p.write_text(GOOD, encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "tools/food/validate_recipe.py"), str(p)],
                       capture_output=True, text=True)
    check("cli на эталоне → exit 0", r.returncode == 0)
    check("cli печатает название", "Паста Болоньезе" in r.stdout)

    r = subprocess.run([sys.executable, str(REPO / "tools/food/validate_recipe.py"),
                        str(p), "--json"], capture_output=True, text=True)
    check("cli --json валиден", _json.loads(r.stdout)["recipe"]["servings"] == 6)

    bad = Path(td) / "битый.md"
    bad.write_text(variant(**{'"servings": 6': '"servings": 0'}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "tools/food/validate_recipe.py"), str(bad)],
                       capture_output=True, text=True)
    check("cli на blocking → exit 1", r.returncode == 1)

print(f"\nvalidate_recipe: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

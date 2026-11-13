#!/usr/bin/env python3
"""Валидатор рецепта-`.md` для раздела «Еда» Personal Hub.

Проверяет, что файл, сгенерированный проектом Claude.ai по `instruction.md`,
будет корректно разобран страницей. Это ЭТАЛОННАЯ РЕАЛИЗАЦИЯ разбора: JS-парсер
страницы обязан давать тот же результат, и это закрепляется контракт-тестом.

Два пути разбора, как в спеке:
  * ```json-блок в конце файла — точный, основной;
  * таблица ингредиентов в markdown — запасной (Perplexity, старые файлы).
Когда есть оба, сверяем их между собой: расхождение — blocking, потому что
дальше молча разъедутся закупка и готовка.

Severity:
  blocking — страница разберёт неверно или не разберёт вовсе;
  warning  — разберёт, но человек на кухне пострадает;
  info     — к сведению.

Запуск:
    validate_recipe.py путь/к/рецепту.md [--json]
Exit 1, если есть blocking. Только stdlib.
"""
import argparse
import json
import re
import sys

# ── стоп-лист (из instruction.md) ────────────────────────────────────────────
# Это ВКУС, а не структура: нарушение — warning, не blocking. Сайдкар его не
# знает вовсе (400 из-за слова «грибы» в заметке о заменах — издевательство).
STOP_WORDS = {
    "креветк": "морепродукты", "кальмар": "морепродукты", "осьминог": "морепродукты",
    "мидии": "морепродукты", "мидий": "морепродукты", "гребешк": "морепродукты",
    "печень": "печень", "печёнк": "печень", "печенк": "печень",
    "гриб": "грибы", "шампиньон": "грибы", "вешенк": "грибы", "трюфел": "грибы",
}

_H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
_META = re.compile(r"^\*\*(.+?):\*\*\s*(.*?)\s*$", re.M)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_STEP = re.compile(r"^###\s+(.+?)\s*$", re.M)
_JSON_BLOCK = re.compile(r"```json\s*\n(.*?)\n```", re.S)
# «Шаг 3. Обжарка фарша (8 мин)» → номер / имя / длительность
_STEP_PARTS = re.compile(r"^Шаг\s*(\d+)\s*[.．]?\s*(.*?)\s*(?:\(([^)]*)\))?\s*$")
_DURATION = re.compile(r"\d+\s*(?:мин|минут|ч|час)", re.I)
# «600 г», «150–200 г», «2,5 л», «1 шт (опционально)»
_QTY = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:[–—-]\s*\d+(?:[.,]\d+)?\s*)?([А-Яа-яA-Za-z.]+)?")
_NO_QTY = re.compile(r"по\s+вкусу|по\s+желанию|щепотк|на\s+глаз", re.I)
_COOKED_WORD = re.compile(r"варён|варен|отварн", re.I)
# Пассивный шаг: «(30 мин, без участия)» — духовка, холодильник, настаивание.
# Ключевое слово ловим и вырезаем из подписи; флаг едет в step["passive"].
# Зеркало _PASSIVE_MD в food.html (контракт «ноль дрейфа»).
_PASSIVE = re.compile(r"без\s+участия|пассивн\w*|ожидание", re.I)


def _issue(sev, cat, msg):
    return {"severity": sev, "category": cat, "message": msg}


def _step_dict(s):
    """Шаг для recipe: title/text + passive, если помечен «без участия»."""
    out = {"title": s["title"], "text": s["text"]}
    if s.get("passive"):
        out["passive"] = True
    return out


def parse_qty(raw):
    """«600 г» → (600.0, 'г'). «по вкусу» → (None, None). Диапазон → нижняя граница."""
    if raw is None:
        return None, None
    s = raw.strip()
    if not s or _NO_QTY.search(s):
        return None, None
    m = _QTY.match(s)
    if not m:
        return None, None
    num = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "").strip(". ") or None
    return num, unit


def clean_name(raw):
    """«Говяжий фарш (80/20)» → «Говяжий фарш». Скобочные уточнения — не часть имени."""
    return re.sub(r"\s*\([^)]*\)\s*", " ", raw or "").strip(" ,;")


def split_sections(text):
    """→ (title, meta{}, sections{имя: тело}). Тело — сырой markdown."""
    title_m = _H1.search(text)
    title = title_m.group(1).strip() if title_m else None

    body_start = title_m.end() if title_m else 0
    first_h2 = _H2.search(text, body_start)
    head = text[body_start:first_h2.start()] if first_h2 else text[body_start:]
    meta = {k.strip(): v.strip() for k, v in _META.findall(head)}

    sections, marks = {}, list(_H2.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections[m.group(1).strip().lower()] = text[m.end():end].strip()
    return title, meta, sections


def parse_ingredients_table(body):
    """Markdown-таблица или список «- имя — 600 г» → [{raw_name, raw_qty}]."""
    out = []
    for ln in (body or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) < 2:
                continue
            # шапка и разделитель зебры
            if set(cells[0]) <= set("-: ") or cells[0].lower().startswith("ингредиент"):
                continue
            out.append({"raw_name": cells[0], "raw_qty": cells[1]})
        elif ln.startswith(("-", "*", "•")):
            item = ln.lstrip("-*• ").strip()
            parts = re.split(r"\s+[—–]\s+|\s*:\s*", item, maxsplit=1)
            if len(parts) == 2:
                out.append({"raw_name": parts[0], "raw_qty": parts[1]})
    return out


def parse_steps(body):
    """### Шаг N. Имя (время) + текст → [{num, name, duration, title, text}].

    Текст ПОСЛЕДНЕГО шага обрывается на ```-блоке. Без этого он вбирал в себя
    машиночитаемый json-хвост файла — и это не косметика: проверка «количество
    продублировано в тексте шага» ищет число в тексте шагов, а json-хвост
    содержит ВСЕ количества по определению. Проверка молча проходила для любого
    файла, где после шагов ничего не следует. Поймано на реальных данных:
    у 21 рецепта она давала «всё хорошо», а после появления раздела
    «Источники» (который обрывал текст) — честное предупреждение.
    """
    steps, marks = [], list(_STEP.finditer(body or ""))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        chunk = body[m.end():end]
        fence = chunk.find("```")
        if fence >= 0:
            chunk = chunk[:fence]
        head = m.group(1).strip()
        passive = bool(_PASSIVE.search(head))
        if passive:
            # ключевое слово и осиротевшие «, )» / «( )» вырезаем — подпись чистая
            head = _PASSIVE.sub("", head)
            head = re.sub(r",\s*\)", ")", head)
            head = re.sub(r"\(\s*\)", "", head).strip()
        p = _STEP_PARTS.match(head)
        num = int(p.group(1)) if p else None
        name = (p.group(2) or "").strip() if p else head
        dur = (p.group(3) or "").strip() if p and p.group(3) else None
        steps.append({"num": num, "name": name, "duration": dur, "passive": passive,
                      "title": head, "text": chunk.strip()})
    return steps


def extract_json_block(text):
    """Последний ```json-блок файла → dict. (None, issue) если не разобрался."""
    blocks = _JSON_BLOCK.findall(text)
    if not blocks:
        return None, None
    try:
        return json.loads(blocks[-1]), None
    except json.JSONDecodeError as e:
        return None, _issue("blocking", "json_block", f"```json-блок не разбирается: {e}")


def parse_recipe(text):
    """→ (recipe, issues). recipe — запись в формате food-recipes@1 (без id)."""
    issues = []
    title, meta, sections = split_sections(text)
    if not title:
        issues.append(_issue("blocking", "title", "нет заголовка `# Название блюда`"))

    block, err = extract_json_block(text)
    if err:
        issues.append(err)

    # ── порции ───────────────────────────────────────────────────────────────
    servings, servings_note = None, meta.get("Порции")
    if block and "servings" in block:
        sv = block["servings"]
        if isinstance(sv, bool) or not isinstance(sv, (int, float)):
            issues.append(_issue("blocking", "servings",
                                 f"servings в json-блоке — не число: {sv!r}"))
        elif sv <= 0:
            issues.append(_issue("blocking", "servings", f"servings должен быть > 0, получено {sv}"))
        else:
            servings = int(sv)
    if servings is None and servings_note:
        # «3 обеда × 2 человека = 6 порций» → 6; иначе «на 4 порции» → 4
        m = re.search(r"=\s*(\d+)", servings_note) or re.search(r"(\d+)\s*порци", servings_note)
        if m:
            servings = int(m.group(1))
            if not block:
                issues.append(_issue("warning", "servings",
                                     f"порции взяты из шапки ({servings}) — в json-блоке их нет"))
    if servings is None:
        issues.append(_issue("blocking", "servings",
                             "не удалось определить число порций — это делитель пересчёта"))

    # ── ингредиенты ──────────────────────────────────────────────────────────
    table = parse_ingredients_table(sections.get("ингредиенты", ""))
    ingredients = []
    if block and isinstance(block.get("ingredients"), list):
        for i, g in enumerate(block["ingredients"]):
            if not isinstance(g, dict):
                issues.append(_issue("blocking", "ingredients", f"ingredients[{i}] — не объект"))
                continue
            q = g.get("qty")
            if isinstance(q, str):
                issues.append(_issue("blocking", "ingredients",
                                     f"«{g.get('name')}»: qty строкой ({q!r}) — при сложении склеится"))
                q = None
            elif isinstance(q, bool):
                issues.append(_issue("blocking", "ingredients", f"«{g.get('name')}»: qty булево"))
                q = None
            nm = (g.get("name") or "").strip()
            if not nm:
                issues.append(_issue("blocking", "ingredients", f"ingredients[{i}]: пустое name"))
            st = g.get("state")
            if st is not None and st not in ("cooked", "dry"):
                issues.append(_issue("blocking", "ingredients",
                                     f"«{nm}»: state={st!r} — допустимы только cooked и dry; "
                                     f"опечатка тихо отключит пересчёт варёного веса"))
                st = None
            # measure — свободный текст для показа («1 стакан»), в КБЖУ/список не
            # идёт. Число сюда класть нельзя: для расчёта есть qty (STD).
            ms = g.get("measure")
            if ms is not None and not isinstance(ms, str):
                issues.append(_issue("blocking", "ingredients",
                                     f"«{nm}»: measure — строка или отсутствует "
                                     f"(это показ, число кладут в qty)"))
                ms = None
            ingredients.append({"name": nm, "raw": nm, "qty": q,
                                "unit": g.get("unit"), "state": st, "measure": ms})
        if table and len(table) != len(ingredients):
            issues.append(_issue("blocking", "ingredients",
                                 f"json-блок и таблица расходятся: {len(ingredients)} против "
                                 f"{len(table)} строк — закупка и готовка разъедутся"))
    else:
        if block is not None:
            issues.append(_issue("blocking", "ingredients", "в json-блоке нет списка ingredients"))
        else:
            issues.append(_issue("warning", "json_block",
                                 "нет ```json-блока — разбираю таблицу эвристикой"))
        for row in table:
            qty, unit = parse_qty(row["raw_qty"])
            ingredients.append({"name": clean_name(row["raw_name"]), "raw": row["raw_name"],
                                "qty": qty, "unit": unit, "state": None})
    if not ingredients:
        issues.append(_issue("blocking", "ingredients", "не найдено ни одного ингредиента"))

    # ── шаги ─────────────────────────────────────────────────────────────────
    steps = parse_steps(sections.get("приготовление", ""))
    if not steps:
        issues.append(_issue("blocking", "steps",
                             "не найдено шагов вида `### Шаг N. Имя (время)`"))

    # ── КБЖУ ─────────────────────────────────────────────────────────────────
    nutrition = None
    if block and isinstance(block.get("nutrition"), dict):
        nutrition = {}
        for k, v in block["nutrition"].items():
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                issues.append(_issue("blocking", "nutrition", f"nutrition.{k} — не число: {v!r}"))
            else:
                nutrition[k] = v

    recipe = {
        "title": title, "cuisine": meta.get("Кухня"),
        "servings": servings, "servings_note": servings_note,
        "time": meta.get("Время"), "difficulty": _difficulty(meta.get("Сложность")),
        "nutrition": nutrition, "ingredients": ingredients,
        "steps": [_step_dict(s) for s in steps],
        "equipment": sections.get("инвентарь"), "storage": sections.get("хранение"),
        "serving": sections.get("советы по подаче"), "sources": sections.get("источники"),
    }
    return recipe, issues, steps


def _difficulty(raw):
    if not raw:
        return None
    m = re.search(r"\d+", raw)
    return int(m.group()) if m else None


def check_atwater(nu, tol=10):
    """Сверка по коэффициентам Этуотера: ккал ≈ 4·Б + 9·Ж + 4·У.

    Единственная проверка КБЖУ, которую МОЖНО сделать без базы нутриентов и без
    знания способа готовки. Она не подтверждает, что числа верны для блюда —
    только что они согласованы между собой. Ловит опечатку в разряде,
    перепутанные местами белки и жиры, случайно оставленные значения от другого
    рецепта.

    Почему нельзя проверить строже. КБЖУ блюда — НЕ сумма сырых ингредиентов:
    при готовке сливается жир, впитывается масло, выпаривается алкоголь, а вода
    уходит или набирается (мясо ужаривается примерно до ¾ массы, крупа
    разваривается втрое). У USDA под это есть таблицы yield factors и nutrient
    retention factors, но для их применения нужна пищевая ценность каждого
    продукта и разметка способа готовки на каждом шаге. Поэтому КБЖУ приходит
    из источника рецепта готовым, а здесь проверяется лишь его внутренняя
    непротиворечивость.

    Допуск 10% намеренно широкий: округление до целых на четырёх числах и
    вариативность самих коэффициентов Этуотера дают до нескольких процентов
    сами по себе (на реальных 21 рецепте разброс уложился в 5,4%).
    """
    issues = []
    kcal = nu.get("kcal")
    if not isinstance(kcal, (int, float)) or isinstance(kcal, bool) or not kcal:
        return issues
    p, f, c = (nu.get("protein_g"), nu.get("fat_g"), nu.get("carb_g"))
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in (p, f, c)):
        return issues
    calc = 4 * p + 9 * f + 4 * c
    if not calc:
        return issues
    dev = (kcal - calc) / calc * 100
    if abs(dev) > tol:
        issues.append(_issue(
            "warning", "nutrition",
            f"КБЖУ не сходится сам с собой: заявлено {kcal:g} ккал, "
            f"а 4·Б+9·Ж+4·У даёт {calc:.0f} ({dev:+.0f}%). "
            f"Проверьте числа — обычно это опечатка в разряде или перепутанные Б и Ж"))
    return issues


def check_quality(recipe, steps, text):
    """Проверки «разберётся, но на кухне будет больно»."""
    issues = []

    nu = recipe.get("nutrition")
    if not nu:
        issues.append(_issue("warning", "nutrition",
                             "нет КБЖУ на порцию — карточка рецепта будет без чисел"))
    else:
        issues += check_atwater(nu)
    if not recipe.get("sources"):
        issues.append(_issue("warning", "sources", "нет раздела «Источники»"))
    if not recipe.get("cuisine"):
        issues.append(_issue("warning", "meta", "не указана кухня"))

    steps_text = " ".join(s["text"] for s in steps)

    for s in steps:
        if not s["name"]:
            issues.append(_issue("warning", "steps",
                                 f"«{s['title']}»: нет короткого имени — оглавление режима "
                                 f"готовки останется пустым"))
        if not s["duration"] or not _DURATION.search(s["duration"] or ""):
            issues.append(_issue("warning", "steps",
                                 f"«{s['title']}»: нет длительности в скобках — бейдж «⏱ N мин» "
                                 f"не появится"))
        words = len(s["text"].split())
        if words > 120:
            issues.append(_issue("warning", "steps",
                                 f"«{s['title']}»: {words} слов — шаг не атомарен, на экране "
                                 f"телефона не поместится"))

    # Главная проверка удобства: количество, которого нет в тексте шага, человек
    # вынужден искать в таблице мокрыми руками. Плюс страница не сможет
    # пересчитать его под выбранные порции — подставлять некуда.
    missing = []
    for g in recipe["ingredients"]:
        if g["qty"] is None:
            continue
        q = g["qty"]
        num = str(int(q)) if float(q).is_integer() else str(q).replace(".", ",")
        if not re.search(r"(?<!\d)" + re.escape(num) + r"(?!\d)", steps_text):
            missing.append(f"{g['name']} ({num}{' ' + g['unit'] if g['unit'] else ''})")
    if missing:
        issues.append(_issue("warning", "inline_qty",
                             "количества не указаны в тексте шагов: " + ", ".join(missing) +
                             " — см. правило 1 в instruction.md"))

    # Название говорит «варёная», а пометки нет → в список покупок уедет вес
    # готовой крупы, то есть в 2,5–3 раза больше нужного. Самая дорогая из
    # тихих ошибок: она не выглядит ошибкой ни в рецепте, ни в списке.
    unmarked = [g["name"] for g in recipe["ingredients"]
                if _COOKED_WORD.search(g["raw"] or g["name"] or "")
                and g.get("state") != "cooked"]
    if unmarked:
        issues.append(_issue("warning", "cooked_state",
                             "вес готового продукта без пометки state=cooked: " +
                             ", ".join(unmarked) +
                             " — купить придётся в 2,5–3 раза меньше, см. правило 4"))

    low = text.lower()
    hits = {label for w, label in STOP_WORDS.items() if w in low}
    if hits:
        issues.append(_issue("warning", "stop_list",
                             "задет стоп-лист: " + ", ".join(sorted(hits)) +
                             " — проверьте, не ингредиент ли это"))
    return issues


def validate(text):
    """→ (recipe, issues). Единая точка входа."""
    recipe, issues, steps = parse_recipe(text)
    issues += check_quality(recipe, steps, text)
    return recipe, issues


def main():
    ap = argparse.ArgumentParser(description="Валидатор рецепта-.md для раздела «Еда»")
    ap.add_argument("path", help="путь к файлу рецепта")
    ap.add_argument("--json", action="store_true", help="выдать разобранный рецепт и issues в JSON")
    a = ap.parse_args()

    with open(a.path, encoding="utf-8") as f:
        text = f.read()
    recipe, issues = validate(text)

    if a.json:
        print(json.dumps({"recipe": recipe, "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print(f"Рецепт: {recipe.get('title') or '—'}")
        print(f"Порций: {recipe.get('servings') or '—'} · "
              f"ингредиентов: {len(recipe['ingredients'])} · шагов: {len(recipe['steps'])}")
        if not issues:
            print("\n✓ замечаний нет")
        for sev in ("blocking", "warning", "info"):
            group = [i for i in issues if i["severity"] == sev]
            if not group:
                continue
            mark = {"blocking": "✗ БЛОКИРУЕТ", "warning": "⚠ предупреждение", "info": "· инфо"}[sev]
            print(f"\n{mark} ({len(group)}):")
            for i in group:
                print(f"  [{i['category']}] {i['message']}")

    return 1 if any(i["severity"] == "blocking" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())

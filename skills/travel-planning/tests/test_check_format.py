#!/usr/bin/env python3
"""
Тесты check_format.py — упор на семантические count-проверки todo_count / poi_count
(дефект, воспроизведённый на двух прогонах Stage 5: YAML 24 vs факт 22).

Запуск:
    python3 skills/travel-planning/tests/test_check_format.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_format as cf  # noqa: E402


passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


# --- фикстуры ----------------------------------------------------------------

def stage5(todo_field: int, n_items: int, *, with_field: bool = True) -> str:
    field = f"todo_verification_items: {todo_field}\n" if with_field else ""
    items = "\n".join(f"- [ ] пункт {i}" for i in range(1, n_items + 1))
    return (
        "---\n"
        "trip_id: t\n"
        "stage: 5_final_plan\n"
        f"{field}"
        "---\n\n"
        "## Маршрут\n\n"
        "День 1 — что-то.\n\n"
        "## TODO для верификации\n\n"
        "### Перед бронированием\n"
        f"{items}\n\n"
        "## Diff\n\nконец.\n"
    )


def stage3(total: int, n_comments: int, *, with_field: bool = True) -> str:
    field = f"total_pois: {total}\n" if with_field else ""
    pois = "\n".join(
        f"#### POI {i}\nтекст\n\nКомментарий пользователя:\n" for i in range(1, n_comments + 1)
    )
    return (
        "---\n"
        "trip_id: t\n"
        "stage: 3_poi_aggregation\n"
        f"{field}"
        "---\n\n"
        "## Ханой\n\n"
        f"{pois}\n"
    )


# --- todo_count --------------------------------------------------------------

check("todo_count: совпадение → пусто", cf.check_todo_count(stage5(3, 3)) == [])
check("todo_count: 24 vs 22 → 1 issue (реальный дефект)",
      len(cf.check_todo_count(stage5(24, 22))) == 1)
check("todo_count: в сообщении факт 22 и заявленное 24",
      "22" in cf.check_todo_count(stage5(24, 22))[0]
      and "24" in cf.check_todo_count(stage5(24, 22))[0])
check("todo_count: поле есть, чекбоксов 0, заявлено 5 → issue",
      len(cf.check_todo_count(stage5(5, 0))) == 1)
check("todo_count: нет секции → неприменимо (пусто)",
      cf.check_todo_count("---\nstage: 4_variants\n---\n\n## Решение\n") == [])
check("todo_count: секция есть, поля нет → issue про отсутствие поля",
      len(cf.check_todo_count(stage5(0, 3, with_field=False))) == 1
      and "нет" in cf.check_todo_count(stage5(0, 3, with_field=False))[0])
check("todo_count: чекбоксы [x]/[X] тоже считаются",
      cf.check_todo_count(
          "---\ntodo_verification_items: 2\n---\n\n"
          "## TODO для верификации\n- [x] a\n- [X] b\n") == [])
check("todo_count: вложенные чекбоксы с отступом считаются",
      cf.check_todo_count(
          "---\ntodo_verification_items: 2\n---\n\n"
          "## TODO для верификации\n- [ ] a\n  - [ ] b\n") == [])
check("todo_count: следующая ## секция не подмешивает чекбоксы",
      cf.check_todo_count(
          "---\ntodo_verification_items: 1\n---\n\n"
          "## TODO для верификации\n- [ ] a\n\n## Другое\n- [ ] x\n- [ ] y\n") == [])

# --- poi_count ---------------------------------------------------------------

check("poi_count: совпадение 59 → пусто", cf.check_poi_count(stage3(59, 59)) == [])
check("poi_count: 59 vs 57 → 1 issue", len(cf.check_poi_count(stage3(59, 57))) == 1)
check("poi_count: сообщение содержит факт 57", "57" in cf.check_poi_count(stage3(59, 57))[0])
check("poi_count: нет total_pois → неприменимо (пусто)",
      cf.check_poi_count(stage3(0, 3, with_field=False)) == [])
check("poi_count: total_pois 0 и 0 комментариев → пусто",
      cf.check_poi_count(stage3(0, 0)) == [])

# --- poi_count: русские категории в заголовках POI (Фаза 1 русификации) -------
# check_poi_count считает поля «Комментарий пользователя», а не категории, →
# должен быть нейтрален к языку категории в заголовке POI.
def stage3_ru_cats(total: int) -> str:
    cats = ["СИЛЬНОЕ ПОДТВЕРЖДЕНИЕ", "СПОРНЫЙ", "КРАСНЫЙ ФЛАГ",
            "СКРЫТАЯ ЖЕМЧУЖИНА", "СЛАБЫЙ СИГНАЛ", "СЛАБОЕ ПОДТВЕРЖДЕНИЕ"]
    pois = "\n".join(
        f"#{i} **Место {i}** (Place {i}) — {cats[(i - 1) % len(cats)]}\n"
        f"1. Регион: Ханой\nКомментарий пользователя:\n"
        for i in range(1, total + 1)
    )
    return (f"---\ntrip_id: t\nstage: 3_poi_aggregation\ntotal_pois: {total}\n"
            f"---\n\n## Ханой\n\n{pois}\n")

check("poi_count: русские категории в заголовках POI → счёт совпал (пусто)",
      cf.check_poi_count(stage3_ru_cats(6)) == [])

# --- frontmatter_integrity ---------------------------------------------------
# Чистый frontmatter (канонический ---) → пусто.
_clean_fm = ("---\ntrip_id: t\nstage: 2_similarity\nhigh_similarity_count: 5\n"
             "---\n\n# Stage 2\n\n## Контекст\n- x\n\n## Распределение\n"
             "|Категория|Кол-во|\n|--|--|\n|HIGH|5|\n")
check("frontmatter_integrity: чистый frontmatter → пусто",
      cf.check_frontmatter_integrity(_clean_fm) == [])

# `-----`-делиметр + правильное закрытие + body-разделители (как Китай 7 июня)
# → пусто (нормализация делиметра + берётся ПЕРВЫЙ close; body-`-----` не мешают).
_dashes_fm = ("-----\ntrip_id: t\nstage: 2_similarity\n-----\n\n# Stage 2\n\n"
              "## Контекст\n- x\n\n-----\n\n## Reading list\n- y\n\n-----\n")
check("frontmatter_integrity: `-----` + body-разделители (Китай-стиль) → пусто",
      cf.check_frontmatter_integrity(_dashes_fm) == [])

# Малформ: markdown протёк в frontmatter (## ключ + ## секция + таблица).
_leaked_fm = ("-----\n\n## trip_id: вьетнам\nstage: 2_similarity\n\n"
              "## Контекст\n- x\n\n## Распределение\n|Категория|N|\n|--|--|\n|HIGH|5|\n\n"
              "-----\n\n## Reading list\n- y\n")
_iss = cf.check_frontmatter_integrity(_leaked_fm)
check("frontmatter_integrity: протёкший markdown → issue", len(_iss) >= 1)
check("frontmatter_integrity: сообщение про markdown в frontmatter",
      any("markdown-разметка" in i for i in _iss))
check("frontmatter_integrity: потерян trip_id (записан как ## trip_id:) → issue",
      any("trip_id" in i for i in _iss))

# Отсутствие обязательного ключа stage.
_nostage = "---\ntrip_id: t\nhigh_similarity_count: 5\n---\n\n# Body\n"
check("frontmatter_integrity: нет stage → issue",
      any("stage" in i for i in cf.check_frontmatter_integrity(_nostage)))

# Нет frontmatter вовсе → не дублируем (зона yaml_delimiters).
check("frontmatter_integrity: нет frontmatter → пусто (не дублирует yaml_delimiters)",
      cf.check_frontmatter_integrity("# Просто body\n\nтекст\n") == [])

# --- presets / реестр --------------------------------------------------------

check("preset stage 2 включает frontmatter_integrity",
      "frontmatter_integrity" in cf.STAGE_CHECKS["2"])
check("frontmatter_integrity во всех пресетах 0–6",
      all("frontmatter_integrity" in cf.STAGE_CHECKS[s] for s in "0123456"))
check("frontmatter_integrity в ALL_CHECKS и CHECK_FUNCS",
      "frontmatter_integrity" in cf.ALL_CHECKS
      and "frontmatter_integrity" in cf.CHECK_FUNCS)

check("preset stage 5 включает todo_count", "todo_count" in cf.STAGE_CHECKS["5"])
check("preset stage 3 включает poi_count", "poi_count" in cf.STAGE_CHECKS["3"])
# Stage 6 (финал) — generic-проверки, без каунтеров (todo/poi).
check("preset stage 6 существует", "6" in cf.STAGE_CHECKS)
check("preset stage 6 — generic (dollar/yaml/frontmatter/parse/placeholders/brevity/save-as)",
      set(cf.STAGE_CHECKS["6"]) ==
      {"dollar_escape", "yaml_delimiters", "frontmatter_integrity",
       "frontmatter_parse", "frontmatter_placeholders",
       "no_for_brevity", "no_save_as_body"})
check("preset stage 6 без каунтеров",
      not ({"todo_count", "poi_count"} & set(cf.STAGE_CHECKS["6"])))
check("todo_count зарегистрирован в CHECK_FUNCS", "todo_count" in cf.CHECK_FUNCS)
check("poi_count зарегистрирован в CHECK_FUNCS", "poi_count" in cf.CHECK_FUNCS)
check("todo_count и poi_count в ALL_CHECKS",
      {"todo_count", "poi_count"} <= cf.ALL_CHECKS)

# --- helpers -----------------------------------------------------------------

check("_yaml_int читает поле", cf._yaml_int("---\ntotal_pois: 12\n---\n", "total_pois") == 12)
check("_yaml_int нет поля → None", cf._yaml_int("---\nx: 1\n---\n", "total_pois") is None)
check("_yaml_int игнорирует совпадение в теле (не frontmatter)",
      cf._yaml_int("---\nx: 1\n---\n\ntotal_pois: 99\n", "total_pois") is None)
check("_section_body нет секции → None",
      cf._section_body("## A\nтекст\n", r"^##\s+TODO") is None)

# ── Stage 0 longlist_count + Stage 1 reports_count (format firewall) ──
def _stage0_ll(declared, n_regions):
    body = "".join(f"### Регион{i}\nтекст\n" for i in range(n_regions))
    return (f"---\nstage: 0_scope\nlonglist_count: {declared}\n---\n"
            f"## Longlist ({n_regions}) — для DR\n{body}\n## Excluded\nx\n")

check("longlist_count: совпадение → пусто", cf.check_longlist_count(_stage0_ll(8, 8)) == [])
check("longlist_count: 8 vs 6 → issue", len(cf.check_longlist_count(_stage0_ll(8, 6))) == 1)
check("longlist_count: нет поля → неприменимо",
      cf.check_longlist_count("## Longlist (3)\n### A\n### B\n### C\n") == [])
check("longlist_count: нет секции → неприменимо",
      cf.check_longlist_count("---\nlonglist_count: 5\n---\nтело\n") == [])

def _stage1_rc(declared, markers):
    return (f"---\nstage: 1_dr_reports\nreports_count: {declared}\n---\n"
            + "".join(f"{m}\n1. URL: http://x\n" for m in markers))

check("reports_count: ## КАРТОЧКА — совпадение",
      cf.check_reports_count(_stage1_rc(2, ["## КАРТОЧКА 1", "## КАРТОЧКА 2"])) == [])
check("reports_count: 3 формата заголовка считаются все",
      cf.check_reports_count(_stage1_rc(3, ["## КАРТОЧКА 1", "**КАРТОЧКА 02**", "### Карточка 3"])) == [])
check("reports_count: диапазон `Карточки 1–30` не считается за маркер",
      cf.check_reports_count("---\nreports_count: 1\n---\n### Карточки 1–30\n## КАРТОЧКА 5\n") == [])
check("reports_count: 99 vs 2 → issue",
      len(cf.check_reports_count(_stage1_rc(99, ["## КАРТОЧКА 1", "## КАРТОЧКА 2"]))) == 1)
check("reports_count: нет поля → неприменимо",
      cf.check_reports_count("## КАРТОЧКА 1\nx\n") == [])

check("STAGE_CHECKS содержит 0/1/2",
      all(s in cf.STAGE_CHECKS for s in ("0", "1", "2")))
check("пресет 0 ⊇ delimiters+integrity+parse+placeholders+longlist_count",
      set(cf.STAGE_CHECKS["0"]) >= {"yaml_delimiters", "frontmatter_integrity",
      "frontmatter_parse", "frontmatter_placeholders", "longlist_count"})
check("пресет 1 ⊇ delimiters+integrity+parse+placeholders+reports_count",
      set(cf.STAGE_CHECKS["1"]) >= {"yaml_delimiters", "frontmatter_integrity",
      "frontmatter_parse", "frontmatter_placeholders", "reports_count"})
check("все пресет-чеки есть в CHECK_FUNCS",
      all(c in cf.CHECK_FUNCS for cs in cf.STAGE_CHECKS.values() for c in cs))

# ── frontmatter_parse (Р5 гейт эмита) + placeholder ──
check("frontmatter_parse: flush/flow валидны → пусто",
      cf.check_frontmatter_parse("---\nregions:\n- Пекин\nweights: [a, b]\ntrip_id: t\n---\n") == [])
check("frontmatter_parse: block-скаляр → FAIL",
      len(cf.check_frontmatter_parse("---\nnote: |\n  x\ntrip_id: t\n---\n")) >= 1)
check("frontmatter_parse: на `-----`-делимитере работает",
      cf.check_frontmatter_parse("-----\nnote: |\n  x\ntrip_id: t\n-----\n") != [])
check("frontmatter_parse: нет frontmatter → пусто",
      cf.check_frontmatter_parse("просто текст\n") == [])
check("placeholder: YYYY-MM-DD ловится",
      len(cf.check_frontmatter_placeholders("---\ndr_run_date: YYYY-MM-DD  # поставь\ntrip_id: t\n---\n")) == 1)
check("placeholder: <шаблон> ловится",
      cf.check_frontmatter_placeholders("---\nfoo: <заполни>\n---\n") != [])
check("placeholder: чистое значение → пусто",
      cf.check_frontmatter_placeholders("---\ndr_run_date: 2026-07-05\n---\n") == [])

# ── trip.yaml (trip-meta@1) ──
def trip_meta(**over):
    base = {"schema": "trip-meta@1", "title": "Северный Вьетнам", "status": "ready",
            "travelers": "[мария, алексей]", "season": '"2026-09"', "updated": "2026-07-10"}
    base.update(over)
    return "\n".join(f"{k}: {v}" for k, v in base.items() if v is not None) + "\n"

check("trip_meta: валидная карточка → пусто", cf.check_trip_meta(trip_meta()) == [])
check("trip_meta: season только год в кавычках → пусто",
      cf.check_trip_meta(trip_meta(season='"2027"')) == [])
check("trip_meta: комментарий после значения не мешает",
      cf.check_trip_meta(trip_meta(status="planning  # прорабатывается")) == [])
check("trip_meta: status вне enum → issue",
      any("вне enum" in i for i in cf.check_trip_meta(trip_meta(status="готов"))))
check("trip_meta: season без кавычек → issue",
      any("КАВЫЧКАХ" in i for i in cf.check_trip_meta(trip_meta(season="2026-09"))))
check("trip_meta: season мусор → issue",
      any("season" in i for i in cf.check_trip_meta(trip_meta(season='"сентябрь 2026"'))))
check("trip_meta: месяц 13 → issue",
      any("01–12" in i for i in cf.check_trip_meta(trip_meta(season='"2026-13"'))))
check("trip_meta: нет title → issue",
      any("`title`" in i for i in cf.check_trip_meta(trip_meta(title=None))))
check("trip_meta: travelers не списком → issue",
      any("flow-списком" in i for i in cf.check_trip_meta(trip_meta(travelers="алексей"))))
check("trip_meta: чужая schema → issue",
      any("trip-meta@1" in i for i in cf.check_trip_meta(trip_meta(schema="trip-meta@2"))))
check("trip_meta: updated кривой → issue",
      any("updated" in i for i in cf.check_trip_meta(trip_meta(updated="10.07.2026"))))

# ── trip.yaml: точные даты start/end (2026-10-03) ──
# Необязательны: поездка без точных дат — нормальное состояние (известен
# только season). Если есть — только парой, ISO без кавычек, end ≥ start.
check("trip_meta: без start/end — валидно (поездка без точных дат)",
      cf.check_trip_meta(trip_meta()) == [])
check("trip_meta: start/end парой по порядку — валидно",
      cf.check_trip_meta(trip_meta(start="2026-09-14", end="2026-09-27")) == [])
check("trip_meta: однодневная поездка (end = start) — валидно",
      cf.check_trip_meta(trip_meta(start="2026-09-14", end="2026-09-14")) == [])
check("trip_meta: только start → issue «парой»",
      any("парой" in i for i in cf.check_trip_meta(trip_meta(start="2026-09-14"))))
check("trip_meta: только end → issue «парой»",
      any("парой" in i for i in cf.check_trip_meta(trip_meta(end="2026-09-27"))))
check("trip_meta: end раньше start → issue",
      any("раньше" in i for i in cf.check_trip_meta(trip_meta(start="2026-09-14", end="2026-09-01"))))
check("trip_meta: start в кавычках → issue формата",
      any("start должен быть датой" in i for i in cf.check_trip_meta(trip_meta(start='"2026-09-14"', end="2026-09-27"))))
check("trip_meta: несуществующая дата 2026-02-30 → issue",
      any("end должен быть датой" in i for i in cf.check_trip_meta(trip_meta(start="2026-02-01", end="2026-02-30"))))
check("trip_meta: dd.mm.yyyy → issue",
      any("start должен быть датой" in i for i in cf.check_trip_meta(trip_meta(start="14.09.2026", end="2026-09-27"))))
# мягкие сигналы — отдельной функцией, не блокируют
check("warnings: ready + месяц — тишина",
      cf.trip_meta_warnings(trip_meta(status="ready", season='"2026-09"')) == [])
check("warnings: ready + только год → предупреждение",
      any("status ready" in w for w in cf.trip_meta_warnings(trip_meta(status="ready", season='"2027"'))))
check("warnings: ready + только год, но есть start/end — тишина",
      cf.trip_meta_warnings(trip_meta(status="ready", season='"2027"', start="2027-05-01", end="2027-05-10")) == [])
check("warnings: planning + только год — тишина (идея, не поездка)",
      cf.trip_meta_warnings(trip_meta(status="planning", season='"2027"')) == [])
check("warnings: start не в месяце season → сверить",
      any("не в месяце season" in w for w in cf.trip_meta_warnings(trip_meta(season='"2026-09"', start="2026-10-02", end="2026-10-12"))))
check("warnings: start в месяце season — тишина",
      cf.trip_meta_warnings(trip_meta(season='"2026-09"', start="2026-09-28", end="2026-10-05")) == [])
check("warnings не попадают в блокирующие issues",
      cf.check_trip_meta(trip_meta(status="ready", season='"2027"')) == [])


print(f"\ncheck_format: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

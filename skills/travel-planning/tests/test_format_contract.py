#!/usr/bin/env python3
"""Drift-тест формат-контрактов (R2a).

Сверяет, что копии формата артефакта согласованы с каноном
`references/stageN/stageN-output-spec.md`. Ловит класс «формат-дрейфа»: копию
переименовали/уронили поле, сменили разделитель/маркер, уехал `reports_count`.

Read-only по файлам — НИЧЕГО не исполняет в прогоне скилла, поэтому безопасен.
Парсер-нога сверки использует только якоря, которые `parse_dr_cards.py`
реально экспонирует (он card-splitter, ростер 20 полей не знает) — полная
роспись полей сверяется между документными копиями.

Запуск: python3 skills/travel-planning/tests/test_format_contract.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
STAGE1 = SKILL / "references" / "stage1"
SCRIPTS = SKILL / "scripts"

sys.path.insert(0, str(SCRIPTS))
import parse_dr_cards as pdc  # noqa: E402
import similarity_score as sim  # noqa: E402
import aggregate_pois as agg  # noqa: E402
import check_format as cf  # noqa: E402
import taxonomy  # noqa: E402
from export import style as st  # noqa: E402

STAGE1_PROMPT = (STAGE1 / "stage1-dr-prompt.md").read_text(encoding="utf-8")
STAGE1_SPEC = (STAGE1 / "stage1-output-spec.md").read_text(encoding="utf-8")

STAGE0 = SKILL / "references" / "stage0"
STAGE2 = SKILL / "references" / "stage2"
STAGE3 = SKILL / "references" / "stage3"
STAGE4 = SKILL / "references" / "stage4"
STAGE5 = SKILL / "references" / "stage5"
STAGE0_SPEC = (STAGE0 / "stage0-output-spec.md").read_text(encoding="utf-8")
STAGE0_REF = (STAGE0 / "stage0-scope.md").read_text(encoding="utf-8")
STAGE2_SPEC = (STAGE2 / "stage2-output-spec.md").read_text(encoding="utf-8")
STAGE2_REF = (STAGE2 / "stage2-similarity.md").read_text(encoding="utf-8")
STAGE3_SPEC = (STAGE3 / "stage3-output-spec.md").read_text(encoding="utf-8")
STAGE3_REF = (STAGE3 / "stage3-poi.md").read_text(encoding="utf-8")
STAGE4_SPEC = (STAGE4 / "stage4-output-spec.md").read_text(encoding="utf-8")
STAGE4_REF = (STAGE4 / "stage4-variants.md").read_text(encoding="utf-8")
STAGE5_SPEC = (STAGE5 / "stage5-output-spec.md").read_text(encoding="utf-8")
STAGE5_REF = (STAGE5 / "stage5-final.md").read_text(encoding="utf-8")

STAGE6 = SKILL / "references" / "stage6"
STAGE6_SPEC = (STAGE6 / "stage6-output-spec.md").read_text(encoding="utf-8")
STAGE6_REF = (STAGE6 / "stage6-final.md").read_text(encoding="utf-8")

ROSTER_ANCHOR = "20 полей (канонические имена):"

# --- счётчик ----------------------------------------------------------------

_checks = 0
_failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    global _checks
    _checks += 1
    if not cond:
        _failures.append(msg)


# --- извлечение росписи полей ----------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _section(text: str, heading: str) -> str:
    """Тело нумерованной секции reference'а (`## 8. …`) до следующей (`## 9. …`).

    Терминатор — именно нумерованный H2: внутри §8 лежит fenced-блок шаблона
    тела со своими `## Распределение …`, и обычный `^## ` резал бы секцию на
    первой же строке шаблона.
    """
    i = text.find(heading)
    if i == -1:
        return ""
    rest = text[i + len(heading):]
    m = re.search(r"^##\s+\d+\.\s", rest, re.MULTILINE)
    return rest[: m.start()] if m else rest


def extract_field_roster(text: str) -> list[tuple[int, str]] | None:
    """Список (номер, нормализованная метка) из блока после ROSTER_ANCHOR.

    Нумерованные пункты `N. ...`; индентованные строки — продолжение метки;
    первая неиндентованная не-нумерованная строка завершает список.
    """
    idx = text.find(ROSTER_ANCHOR)
    if idx == -1:
        return None
    block = text[idx + len(ROSTER_ANCHOR):]
    fields: list[tuple[int, str]] = []
    cur: tuple[int, str] | None = None
    for line in block.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            if cur is not None:
                fields.append(cur)
            cur = (int(m.group(1)), m.group(2).strip())
        elif cur is not None:
            stripped = line.strip()
            if not stripped:
                continue
            if line[:1].isspace():
                cur = (cur[0], (cur[1] + " " + stripped).strip())
            else:
                break
    if cur is not None:
        fields.append(cur)
    return [(n, _norm(lbl)) for n, lbl in fields]


def rosters_equal(a, b) -> bool:
    return a is not None and b is not None and a == b


# --- проверки ---------------------------------------------------------------

def test_roster_extractable_and_20() -> None:
    src = extract_field_roster(STAGE1_PROMPT)
    check(src is not None, "ростер не найден в stage1-dr-prompt.md (§6 anchor)")
    if src is not None:
        check(len(src) == 20, f"ожидалось 20 полей в §6, найдено {len(src)}")
        check([n for n, _ in src] == list(range(1, 21)),
              f"номера полей §6 не 1..20: {[n for n, _ in src]}")


def test_canon_roster_matches_source() -> None:
    src = extract_field_roster(STAGE1_PROMPT)
    canon = extract_field_roster(STAGE1_SPEC)
    check(canon is not None, "ростер не найден в stage1-output-spec.md")
    if canon is not None:
        check(len(canon) == 20, f"ожидалось 20 полей в каноне, найдено {len(canon)}")
    check(rosters_equal(src, canon),
          "роспись 20 полей в каноне разошлась с §6 stage1-dr-prompt.md — "
          "синхронизируй stage1-output-spec.md часть 1 с §6 (733–767)")


def test_marker_canon_and_tolerance() -> None:
    # канон объявляет канон-маркер и терпимый
    check("## КАРТОЧКА N" in STAGE1_SPEC,
          "канон не объявляет канон-маркер `## КАРТОЧКА N`")
    check("**КАРТОЧКА N**" in STAGE1_SPEC,
          "канон не перечисляет терпимый маркер `**КАРТОЧКА N**`")
    # парсер реально матчит обе формы
    check(bool(pdc.CARD_MARKER_PATTERN.search("## КАРТОЧКА 1")),
          "CARD_MARKER_PATTERN не матчит канон `## КАРТОЧКА 1`")
    check(bool(pdc.CARD_MARKER_PATTERN.search("**КАРТОЧКА 1**")),
          "CARD_MARKER_PATTERN не матчит терпимый `**КАРТОЧКА 1**`")
    # и НЕ матчит заголовок-диапазон `Карточки 1–30`
    check(not pdc.CARD_MARKER_PATTERN.search("## Карточки 1–30"),
          "CARD_MARKER_PATTERN ложно матчит диапазон `Карточки 1–30`")


def test_separator_canon_and_tolerance() -> None:
    check("`---`" in STAGE1_SPEC, "канон не объявляет разделитель `---`")
    check(bool(pdc.SEP_LINE_RE.match("---")), "SEP_LINE_RE не матчит канон `---`")
    check(bool(pdc.SEP_LINE_RE.match("-----")),
          "SEP_LINE_RE не терпит `-----`")
    check(not pdc.SEP_LINE_RE.match("--"),
          "SEP_LINE_RE ложно матчит `--` (2 дефиса)")


def test_reports_count_top_level() -> None:
    # канон объявляет top-level reports_count
    check("reports_count: N" in STAGE1_SPEC,
          "канон не содержит шаблон `reports_count: N`")
    # парсер матчит верхнеуровневый и НЕ матчит съехавший под отступ
    check(bool(pdc.REPORTS_COUNT_PATTERN.search("reports_count: 56")),
          "REPORTS_COUNT_PATTERN не матчит top-level `reports_count: 56`")
    check(not pdc.REPORTS_COUNT_PATTERN.search("  reports_count: 56"),
          "REPORTS_COUNT_PATTERN ложно матчит индентованный (съехавший) reports_count")


def test_gotchas_present() -> None:
    # часть 3 документирует известные дрейфы (reading-aid)
    check("Часть 3" in STAGE1_SPEC, "в каноне нет части 3 (известные дрейфы)")
    check("-----" in STAGE1_SPEC, "часть 3 не упоминает дрейф разделителя `-----`")
    check("Поле 14" in STAGE1_SPEC or "поле 14" in STAGE1_SPEC,
          "часть 3 не упоминает дрейф формы поля 14")


def test_negative_self_check() -> None:
    """Тест обязан краснеть на порчу копии — иначе он декоративен."""
    canon = extract_field_roster(STAGE1_SPEC)
    # порча: переименуем поле 14
    corrupted = [(n, ("ИСПОРЧЕНО" if n == 14 else lbl)) for n, lbl in (canon or [])]
    check(not rosters_equal(corrupted, canon),
          "NEGATIVE-тест провален: rosters_equal не заметил порчу поля 14")
    # порча: уроним поле 20
    dropped = [(n, lbl) for n, lbl in (canon or []) if n != 20]
    check(not rosters_equal(dropped, canon),
          "NEGATIVE-тест провален: rosters_equal не заметил пропажу поля 20")


# --- Stage 2: канон ↔ similarity_score.py ↔ reference ----------------------

STAGE2_CATEGORIES = ["HIGH", "MEDIUM", "LOW", "OUTLIER", "UNSCORED"]


def test_stage2_components_match_script() -> None:
    expected = ["style", "focus", "pace", "independence", "depth", "demo"]
    check(sim.COMPONENT_NAMES == expected,
          f"COMPONENT_NAMES в similarity_score.py изменились: {sim.COMPONENT_NAMES}")
    for comp in sim.COMPONENT_NAMES:
        check(comp in STAGE2_SPEC,
              f"канон Stage2 не содержит компонент `{comp}` (рассинхрон со скриптом)")
    check(str(sim.DEFAULT_HIGH_THRESHOLD) in STAGE2_SPEC,
          f"канон Stage2 не фиксирует порог HIGH {sim.DEFAULT_HIGH_THRESHOLD}")


def test_stage2_categories_consistent() -> None:
    """Канон Фазы 2b: EN-ключ (YAML/payload) И RU-ярлык (тело) — оба в спеке."""
    for cat in STAGE2_CATEGORIES:
        check(cat in STAGE2_SPEC, f"канон Stage2 не содержит EN-ключ {cat}")
        check(cat in STAGE2_REF, f"stage2-similarity.md не содержит EN-ключ {cat}")
        ru = taxonomy.label("author_category", cat)
        check(ru in STAGE2_SPEC,
              f"канон Stage2 не содержит RU-ярлык `{ru}` категории {cat} "
              f"(Фаза 2b: тело эмитится русским)")
        check(ru in STAGE2_REF,
              f"stage2-similarity.md не содержит RU-ярлык `{ru}` категории {cat}")


def test_stage2_body_template_is_russian() -> None:
    """§8 (шаблон тела) Stage 2 — русские ярлыки; YAML-блок — английские ключи."""
    body = _section(STAGE2_REF, "## 8. Структура выходного файла")
    check(body != "", "не найдена §8 stage2-similarity.md (шаблон тела)")
    for cat in STAGE2_CATEGORIES:
        ru = taxonomy.label("author_category", cat)
        check(ru in body,
              f"шаблон тела Stage2 (§8) не содержит RU-ярлык `{ru}` — "
              f"эмит остался английским")
    # Severity warnings в теле — русским словом.
    for key in ("critical", "borderline", "info"):
        ru = taxonomy.label("warning_severity", key)
        check(f"{ru}:" in body,
              f"шаблон тела Stage2 (§8) не содержит severity-ярлык `{ru}:`")
    # YAML-счётчики остаются английскими ключами (машинный слой).
    for field in ("high_similarity_count", "outlier_count", "unscored_count"):
        check(field in body, f"шаблон тела Stage2 (§8) потерял YAML-поле `{field}`")
    # Конкретные строки эмита (не просто присутствие токена).
    check("({category_label})" in body,
          "компактный per-author (§8) не берёт ярлык из `{category_label}` — "
          "модель будет переводить категорию сама (дрейф)")
    check("### Обязательные (ВЫСОКАЯ)" in body,
          "H3 reading list (§8) не в русской форме `### Обязательные (ВЫСОКАЯ)`")
    check("### ОСОБЫЙ СИГНАЛ" in body,
          "H3 reading list (§8) не в русской форме `### ОСОБЫЙ СИГНАЛ`")
    check("### Расширенный список (СРЕДНЯЯ ≥ 6.5)" in body,
          "H3 reading list (§8) не в русской форме "
          "`### Расширенный список (СРЕДНЯЯ ≥ 6.5)`")
    # Якоря парсинга НЕ переводятся (решение: только таксоны).
    check("SIGNAL:" in body, "шаблон тела Stage2 (§8) потерял якорь `SIGNAL:`")
    check("C1 style" in body or "C1 {value}" in body,
          "шаблон тела Stage2 (§8) потерял компонентные строки (Р5: остаются EN)")


# --- Stage 3: канон ↔ aggregate_pois.py ↔ reference ↔ consumer (ось B) ------

def _has_cat(text: str, ckey: str) -> bool:
    return ckey in text or ckey.replace("_", " ") in text


def test_stage3_categories_match_script() -> None:
    """Канон Фазы 2b: EN-ключ (YAML/payload) И RU-ярлык (тело) — оба в спеке."""
    cats = list(agg.CATEGORY_RANK.keys())
    check(len(cats) == 6, f"CATEGORY_RANK не 6 категорий: {cats}")
    for ckey in cats:
        disp = ckey.replace("_", " ")
        check(disp in STAGE3_SPEC, f"канон Stage3 не содержит EN-ключ `{disp}`")
        check(_has_cat(STAGE3_REF, ckey), f"stage3-poi.md не содержит EN-ключ `{ckey}`")
        ru = taxonomy.label("poi_category", ckey)
        check(ru in STAGE3_SPEC,
              f"канон Stage3 не содержит RU-ярлык `{ru}` категории {ckey} "
              f"(Фаза 2b: тело эмитится русским)")
        check(ru in STAGE3_REF,
              f"stage3-poi.md не содержит RU-ярлык `{ru}` категории {ckey}")
    check(agg.VALID_AUTHOR_CATEGORIES == {"HIGH", "OUTLIER", "MEDIUM", "LOW"},
          f"VALID_AUTHOR_CATEGORIES изменились: {agg.VALID_AUTHOR_CATEGORIES}")


def test_stage3_body_template_is_russian() -> None:
    """§8 (шаблон тела) Stage 3 — русские ярлыки; YAML-счётчики — EN-ключи."""
    body = _section(STAGE3_REF, "## 8. Структура выходного файла")
    check(body != "", "не найдена §8 stage3-poi.md (шаблон тела)")
    for ckey in agg.CATEGORY_RANK:
        ru = taxonomy.label("poi_category", ckey)
        check(ru in body,
              f"шаблон тела Stage3 (§8) не содержит RU-ярлык `{ru}` — "
              f"эмит остался английским")
    # Счётчики авторов в полях 2–3 POI — русскими ярлыками.
    for akey in ("HIGH", "OUTLIER", "MEDIUM", "LOW"):
        ru = taxonomy.label("author_category", akey)
        check(ru in body,
              f"шаблон тела Stage3 (§8) не содержит RU-ярлык автора `{ru}`")
    # YAML-счётчики остаются английскими ключами (машинный слой).
    for field in ("strong_confirmed", "hidden_gems", "red_flags", "low_signal"):
        check(field in body, f"шаблон тела Stage3 (§8) потерял YAML-поле `{field}`")
    # Якоря парсинга НЕ переводятся (решение: только таксоны).
    for anchor in ("#### Cluster:", "**Combined with:**", "**Iconic exception:**"):
        check(anchor in body,
              f"шаблон тела Stage3 (§8) потерял якорь парсинга `{anchor}`")
    # Конкретные строки эмита, а не просто присутствие токена: именно они
    # определяют, что напишет модель.
    check("— {category_label}" in body,
          "шаблон заголовка POI (§8) не берёт ярлык из `{category_label}` — "
          "модель будет переводить категорию сама (дрейф)")
    check("— {cluster_category_label}" in body,
          "шаблон cluster-header (§8) не берёт ярлык из `{cluster_category_label}`")
    check(re.search(r"^2\. ВЫСОКАЯ: \{high_count\}", body, re.MULTILINE),
          "поле 2 POI (§8) не в русской форме `2. ВЫСОКАЯ: {high_count} (…)`")
    check(re.search(r"^3\. ОСОБЫЙ СИГНАЛ / СРЕДНЯЯ / НИЗКАЯ:", body, re.MULTILINE),
          "поле 3 POI (§8) не в русской форме "
          "`3. ОСОБЫЙ СИГНАЛ / СРЕДНЯЯ / НИЗКАЯ: …`")


def test_stage3_label_verbatim_rule() -> None:
    """Анти-дрейф: спека велит копировать label из JSON, а скрипт его отдаёт."""
    for tok in ("category_label", "cluster_category_label"):
        check(tok in STAGE3_REF,
              f"stage3-poi.md не упоминает `{tok}` — правило «копируй ярлык "
              f"вербатим» без источника ярлыка не работает")
    pois, _ = agg.process_pois([{
        "name_ru": "A", "region": "r", "cluster_id": "c1",
        "cluster_name_ru": "Кластер",
        "mentions": [{"author_id": "a1", "author_category": "HIGH",
                      "tonality": "recommend"}],
    }], 3)
    check(pois[0].get("category_label") == taxonomy.label(
        "poi_category", pois[0]["category"]),
        "aggregate_pois: category_label не совпадает с taxonomy.label")
    clusters, _ = agg.build_clusters(pois, 3, None, "scarce")
    check(bool(clusters), "build_clusters не собрал кластер на фикстуре")
    check(clusters and clusters[0].get("cluster_category_label")
          == taxonomy.label("poi_category", clusters[0]["cluster_category"]),
          "aggregate_pois: clusters[].cluster_category_label отсутствует или "
          "не совпадает с taxonomy.label")


def test_stage3_consumer_axis_b() -> None:
    # ось B: потребитель stage4 ссылается на поля артефакта Stage 3
    for tok in ("Комментарий пользователя", "commonly_combined_with", "mode_per_region"):
        check(tok in STAGE3_SPEC, f"канон Stage3 не содержит `{tok}`")
        check(tok in STAGE4_REF,
              f"потребитель stage4-variants.md не содержит `{tok}` (рассинхрон оси B)")


# --- Stage 5: канон ↔ check_format.py ↔ reference --------------------------

STAGE5_SECTIONS = [
    "## Контекст и ключевые параметры", "## Шапка",
    "## Критические подготовительные пункты", "## Маршрут по дням",
    "## Сводные таблицы", "## План реагирования на риски",
    "## Чеклист за 2 недели до поездки", "## Diff с предыдущим планом",
    "## TODO для верификации",
]


def test_stage5_sections_and_todo() -> None:
    check(len(STAGE5_SECTIONS) == 9, "ожидалось 9 секций Stage5")
    for sec in STAGE5_SECTIONS:
        check(sec in STAGE5_SPEC, f"канон Stage5 не содержит секцию `{sec}`")
    check("todo_count" in cf.STAGE_CHECKS["5"],
          "check_format STAGE_CHECKS['5'] потерял todo_count (рассинхрон)")
    check("todo_verification_items" in STAGE5_SPEC,
          "канон Stage5 не содержит `todo_verification_items`")
    check("## TODO для верификации" in STAGE5_REF,
          "stage5-final.md не содержит секцию `## TODO для верификации`")
    for icon in ("📍", "🏨", "🎯", "💰"):
        check(icon in STAGE5_SPEC, f"канон Stage5 не содержит иконку дня {icon}")


# --- Stage 4: канон ↔ check_format.py ↔ reference --------------------------

STAGE4_AXES = [
    "Культурное наполнение", "Физическая нагрузка", "Погодные риски",
    "Логистическая сложность", "Соответствие профилю", "Соответствие сезону",
    "Cost rank", "Уникальный риск",
]


def test_stage4_axes_and_decision() -> None:
    for ax in STAGE4_AXES:
        check(ax in STAGE4_SPEC, f"канон Stage4 не содержит ось `{ax}`")
        check(ax in STAGE4_REF, f"stage4-variants.md не содержит ось `{ax}`")
    check("decision_empty" in cf.STAGE_CHECKS["4"],
          "check_format STAGE_CHECKS['4'] потерял decision_empty")
    check("**Выбран вариант:**" in STAGE4_SPEC,
          "канон Stage4 не содержит `**Выбран вариант:**`")
    check("**Выбран вариант:**" in STAGE4_REF,
          "stage4-variants.md не содержит `**Выбран вариант:**`")
    check("10 осей" in STAGE4_SPEC, "канон Stage4 не фиксирует потолок 10 осей")


# --- Stage 0: канон ↔ reference (без скрипта) ------------------------------

def test_stage0_contract_consistent() -> None:
    check("0_scope" in STAGE0_SPEC, "канон Stage0 не упоминает stage `0_scope`")
    for tok in ("#### ", "trip_wishes", "Предложенные пакеты"):
        check(tok in STAGE0_SPEC, f"канон Stage0 не содержит `{tok}`")
        check(tok in STAGE0_REF, f"stage0-scope.md не содержит `{tok}`")


# --- Stage 0: язык тела (Фаза 2b) — спека ↔ реальный парсер stage0.py -------

def test_stage0_roles_russian_and_parsed() -> None:
    """Роли в теле — русские ярлыки, И `_ROLE_HEADING_RE` их реально матчит.

    Ловит ровно ту ловушку, ради которой правки шли одним батчем: перевели
    заголовки role-групп в спеке, а матчер экспорта остался EN-only → секции
    `## Region universe` тихо теряют role-классификацию.
    """
    from export.stages import stage0 as s0  # noqa: E402
    for key in ("core", "supporting", "niche", "borderline"):
        # YAML-ключ роли остаётся английским.
        check(f"`{key}`" in STAGE0_REF,
              f"stage0-scope.md потерял YAML-ключ роли `{key}`")
        # Заголовок role-группы в теле — русским ярлыком.
        group_ru = taxonomy.label("region_role_group", key)
        check(group_ru in STAGE0_REF,
              f"stage0-scope.md не содержит RU-ярлык группы `{group_ru}` "
              f"(Фаза 2b: тело эмитится русским)")
        # ГЛАВНОЕ: парсер экспорта реально резолвит этот заголовок.
        m = s0._ROLE_HEADING_RE.match(f"{group_ru} (4)")
        check(m is not None and s0._normalize_role(m.group(1)) == key,
              f"stage0._ROLE_HEADING_RE не распознаёт RU-заголовок группы "
              f"«{group_ru} (4)» → role `{key}` (матчер отстал от спеки)")
        # Легаси EN-заголовок продолжает резолвиться.
        en = taxonomy.label("region_role_group", key, "en")
        m_en = s0._ROLE_HEADING_RE.match(f"{en} (4) — ядро поездки")
        check(m_en is not None and s0._normalize_role(m_en.group(1)) == key,
              f"stage0._ROLE_HEADING_RE потерял легаси EN-заголовок «{en}»")


def test_stage0_tempo_values_russian_and_rendered() -> None:
    """Значения темпа в прозе — русские, и совпадают со словарём рендерера.

    Спека просит писать «сбалансированный»; `cover_common._TEMPO_RU` печатает
    то же слово для легаси-`balanced`. Разойдутся — в одном артефакте будут
    два разных русских слова для одного темпа.
    """
    from export import cover_common as cc  # noqa: E402
    for key in ("slow", "balanced", "active"):
        check(f"`{key}`" in STAGE0_REF,
              f"stage0-scope.md потерял YAML-ключ темпа `{key}`")
        ru = cc._TEMPO_RU[key]
        check(ru in STAGE0_REF,
              f"stage0-scope.md не содержит RU-значение темпа `{ru}` "
              f"(рендерер печатает именно его — cover_common._TEMPO_RU)")
    check(cc.looks_like_tempo("сбалансированный"),
          "cover_common.looks_like_tempo не принимает русское значение темпа")


def test_stage0_tempo_section_anchor_bilingual() -> None:
    """Секция темпа переименована в спеке → матчер экспорта знает оба языка."""
    from export.stages import stage0 as s0  # noqa: E402
    check("## Темп и распределение по странам" in STAGE0_REF,
          "stage0-scope.md не содержит русский заголовок секции темпа")
    check("Темп и распределение по странам".startswith(s0._TEMPO_H2_PREFIX),
          "stage0._TEMPO_H2_PREFIX не матчит русский заголовок секции темпа")
    check("Tempo + country quota".startswith(s0._TEMPO_H2_PREFIX),
          "stage0._TEMPO_H2_PREFIX потерял легаси-заголовок `Tempo + country quota`")


def test_stage2_severity_prefixes_bilingual() -> None:
    """Severity warnings в теле — русские, и stage2.py их реально разбирает."""
    from export.stages import stage2 as s2  # noqa: E402
    warns, infos = s2._split_warnings_by_severity(
        ["⚠️ критично: узкая выборка", "погранично: пусто", "ℹ️ инфо: заметка"])
    check(warns == ["узкая выборка", "пусто"],
          f"stage2 не разбирает русские severity-префиксы: {warns}")
    check(infos == ["заметка"], f"stage2 не разбирает русское `инфо:`: {infos}")
    legacy_w, legacy_i = s2._split_warnings_by_severity(
        ["⚠️ critical: x", "info: y"])
    check(legacy_w == ["x"] and legacy_i == ["y"],
          "stage2 потерял легаси EN severity-префиксы")


def test_stage3_counts_lines_bilingual() -> None:
    """Поля 2–3 POI переведены в спеке → парсер stage3.py знает обе формы."""
    from export.stages import stage3 as s3  # noqa: E402
    check(s3._classify_field("ВЫСОКАЯ: 3 (рекоменд. 2 · нейтр. 1)") == "high",
          "stage3._classify_field не распознаёт русское поле 2")
    check(s3._classify_field("ОСОБЫЙ СИГНАЛ / СРЕДНЯЯ / НИЗКАЯ: 1 / 2 / 0") == "oml",
          "stage3._classify_field не распознаёт русское поле 3")
    check(s3._classify_field("HIGH упомянули: 3 (рекоменд. 2)") == "high",
          "stage3._classify_field потерял легаси поле 2")
    check(s3._classify_field("OUTLIER / MEDIUM / LOW упомянули: 1 / 2 / 0") == "oml",
          "stage3._classify_field потерял легаси поле 3")
    m = s3._HIGH_COUNTS_RE.search("ВЫСОКАЯ: 3 (рекоменд. 2 · нейтр. 1 · критик. 0)")
    check(m is not None and m.groups()[:4] == ("3", "2", "1", "0"),
          "stage3._HIGH_COUNTS_RE не разбирает русскую форму поля 2")
    m = s3._OML_COUNTS_RE.search("ОСОБЫЙ СИГНАЛ / СРЕДНЯЯ / НИЗКАЯ: 1 / 2 / 0")
    check(m is not None and m.groups() == ("1", "2", "0"),
          "stage3._OML_COUNTS_RE не разбирает русскую форму поля 3")


# --- Stage 6: канон ↔ парсер (stage6.py) ↔ reference -----------------------

STAGE6_SECTIONS = [
    "## Координаты маршрута", "## Дорожное досье",
    "## Бронирования", "## Углубления",
]


def test_stage6_contract_consistent() -> None:
    # 4 секции присутствуют в каноне И в reference.
    for sec in STAGE6_SECTIONS:
        check(sec in STAGE6_SPEC, f"канон Stage6 не содержит секцию `{sec}`")
        check(sec in STAGE6_REF, f"stage6-final.md не содержит секцию `{sec}`")
    # Формат блока координат — колонки + порядок + рёбра — в каноне.
    for tok in ("**Маршрут:**", "**Рёбра:**", "lat", "lon", "Источник", "Точка"):
        check(tok in STAGE6_SPEC, f"канон Stage6 не содержит `{tok}`")
    # source_plan — критичный для рендера, в каноне.
    check("source_plan" in STAGE6_SPEC, "канон Stage6 не содержит `source_plan`")
    # Ключевые слова типа ребра в каноне.
    for kw in ("обычное", "узкое звено", "перелёт"):
        check(kw in STAGE6_SPEC, f"канон Stage6 не содержит тип ребра `{kw}`")
    # ГЛАВНОЕ: канонные ключевые слова реально распознаёт ПАРСЕР (stage6._edge_kind).
    # Если кто-то сменит слово в каноне, но не в парсере (или наоборот) — красный.
    from export.stages import stage6 as s6  # noqa: E402
    check(s6._edge_kind("Ниньбинь → Сапа: лимузин, узкое звено") == "long",
          "stage6._edge_kind не распознаёт «узкое звено» как long")
    check(s6._edge_kind("рейс VN1234, перелёт") == "air",
          "stage6._edge_kind не распознаёт «перелёт» как air")
    check(s6._edge_kind("лимузин · 2 ч") == "normal",
          "stage6._edge_kind не считает обычный переезд normal")
    # Колонки координатной таблицы реально матчатся парсером (_col_index).
    header = ["№", "Точка", "lat", "lon", "Источник", "Дни"]
    check(s6._col_index(header, "точк", "регион", "место") == 1,
          "stage6._col_index не находит колонку имени")
    check(s6._col_index(header, "lat", "шир") == 2 and s6._col_index(header, "lon", "долг") == 3,
          "stage6._col_index не находит lat/lon")
    # check_format знает про Stage 6 (generic-проверки).
    check("6" in cf.STAGE_CHECKS, "check_format STAGE_CHECKS не содержит `6`")


def test_taxonomy_axis():
    """Ось taxonomy (Фаза 1 русификации): ключи словаря ↔ константам скриптов
    1:1; pattern() каждой группы матчит и EN, и RU ярлыки. Спеки не трогаются."""
    # (а) Ключи групп ↔ константы скриптов / style.
    check(set(taxonomy.keys("poi_category")) == set(agg.CATEGORY_RANK),
          "taxonomy poi_category != aggregate_pois.CATEGORY_RANK")
    check(set(taxonomy.keys("poi_category_badge")) == set(agg.CATEGORY_RANK),
          "taxonomy poi_category_badge != CATEGORY_RANK (6 категорий)")
    check(set(agg.VALID_AUTHOR_CATEGORIES) <= set(taxonomy.keys("author_category")),
          "VALID_AUTHOR_CATEGORIES не подмножество taxonomy author_category")
    check(set(taxonomy.keys("tonality")) == set(agg.VALID_TONALITIES),
          "taxonomy tonality != aggregate_pois.VALID_TONALITIES")
    check(set(taxonomy.keys("similarity_component")) == set(sim.COMPONENT_NAMES),
          "taxonomy similarity_component != similarity_score.COMPONENT_NAMES")
    check(set(taxonomy.keys("region_role")) == set(st.ROLE_BADGES),
          "taxonomy region_role != style.ROLE_BADGES")
    # CATEGORY_SHORT/CATEGORY_COLORS ключи (space-EN) == EN-ярлыки poi_category.
    en_poi = {taxonomy.label("poi_category", k, "en")
              for k in taxonomy.keys("poi_category")}
    check(set(st.CATEGORY_SHORT) == en_poi,
          "style.CATEGORY_SHORT ключи != EN-ярлыки taxonomy poi_category")
    check(set(st.CATEGORY_COLORS) == en_poi,
          "style.CATEGORY_COLORS ключи != EN-ярлыки taxonomy poi_category")

    # (б) pattern() каждой группы матчит EN и RU ярлыки всех ключей.
    for g in taxonomy.groups():
        pat = taxonomy.pattern(g)
        for k in taxonomy.keys(g):
            check(re.fullmatch(pat, taxonomy.label(g, k, "en")) is not None,
                  f"pattern({g}) не матчит EN-ярлык {k}")
            check(re.fullmatch(pat, taxonomy.label(g, k, "ru")) is not None,
                  f"pattern({g}) не матчит RU-ярлык {k}")


def test_taxonomy_consumers_axis():
    """Ось Р2: экспортные группы taxonomy ↔ потребители в stages_html (1:1).

    Каждая видимая-в-экспорте группа должна реально использоваться рендерером
    (иначе группа-сирота — дрейф словаря vs код). Обратную сторону («рендерер
    ссылается на несуществующую группу») ловят smoke-тесты test_html_export
    (рендер фикстуры вызовет taxonomy.label → ValueError на битой группе)."""
    ht = SCRIPTS / "export" / "stages_html"
    src = "\n".join(p.read_text(encoding="utf-8") for p in ht.glob("*.py"))
    export_groups = ["author_category", "poi_category_badge", "content_density",
                     "report_focus", "report_tonality", "region_role_group",
                     "similarity_component"]
    for group in export_groups:
        check(f'"{group}"' in src or f"'{group}'" in src,
              f"taxonomy-группа {group} не используется ни одним stages_html-рендерером")

    # `author_tag` (Р11, батч 2, §5.3) — единственная группа, живущая только в
    # RL-ветке: строки идут в JSON интерактивного Stage 2 (`%%DATA%%`),
    # stages_html её не рендерит вовсе. Зеркальная ось той же формы, но по
    # реальному потребителю.
    rl_stage2_src = (SCRIPTS / "export" / "stages" / "stage2.py").read_text(encoding="utf-8")
    check('"author_tag"' in rl_stage2_src,
          "taxonomy-группа author_tag не используется stages/stage2.py")

    # Группы Фазы 2a живут в RL-ветке общим хелпером, который зовут ОБА
    # рендерера (HT импортирует его из stages/) — ось по реальному владельцу.
    rl_stage1_src = (SCRIPTS / "export" / "stages" / "stage1.py").read_text(encoding="utf-8")
    check('"report_style"' in rl_stage1_src,
          "taxonomy-группа report_style не используется stages/stage1.py")
    rl_stage0_src = (SCRIPTS / "export" / "stages" / "stage0.py").read_text(encoding="utf-8")
    for group in ("scope_labels", "scope_format"):
        check(f'"{group}"' in rl_stage0_src,
              f"taxonomy-группа {group} не используется stages/stage0.py")


def main() -> int:
    for fn in (
        test_taxonomy_axis,
        test_taxonomy_consumers_axis,
        test_roster_extractable_and_20,
        test_canon_roster_matches_source,
        test_marker_canon_and_tolerance,
        test_separator_canon_and_tolerance,
        test_reports_count_top_level,
        test_gotchas_present,
        test_negative_self_check,
        test_stage2_components_match_script,
        test_stage2_categories_consistent,
        test_stage2_body_template_is_russian,
        test_stage3_categories_match_script,
        test_stage3_body_template_is_russian,
        test_stage3_label_verbatim_rule,
        test_stage3_consumer_axis_b,
        test_stage5_sections_and_todo,
        test_stage4_axes_and_decision,
        test_stage0_contract_consistent,
        test_stage6_contract_consistent,
        # Ось «язык тела» (Фаза 2b): спека ↔ реальный матчер экспорта.
        test_stage0_roles_russian_and_parsed,
        test_stage0_tempo_values_russian_and_rendered,
        test_stage0_tempo_section_anchor_bilingual,
        test_stage2_severity_prefixes_bilingual,
        test_stage3_counts_lines_bilingual,
    ):
        fn()
    if _failures:
        print(f"FAIL — {len(_failures)}/{_checks} проверок упали:")
        for f in _failures:
            print(f"  ✗ {f}")
        return 1
    print(f"OK — все {_checks} проверок пройдены (формат-контракты Stage 0–6)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

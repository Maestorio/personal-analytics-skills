"""polish_check.py — sanity-checker для polish-step'а перед PDF-рендером.

**Контракт формата** артефактов (секции/числа, которые polish не должен ломать) —
каноны `references/stage{4,5}/stageN-output-spec.md`; сверка —
`tests/test_format_contract.py`.

Polish (см. `references/stage5/stage5-polish-prompt.md`) — LLM-шаг,
который переписывает сырой `5_final_plan.md` в presentation-grade форму.
LLM не детерминированна и может что-нибудь случайно сломать:
  - дропнуть день из маршрута
  - изменить ключевое число (цена, длительность)
  - «улучшить» структуру и поломать downstream-парсеры

Этот скрипт сравнивает оригинал и polished версию по нескольким
численным метрикам. Если расхождение слишком большое — abort, polish
надо переделать.

Usage (CLI):
    python3 polish_check.py --source 5_final_plan.md --polished polished.md
    # exit 0 → safe; exit 1 → violations; exit 2 → usage error

Usage (Python):
    from polish_check import check_polish
    report = check_polish(source_text, polished_text)
    if report.ok:
        ...
    else:
        for v in report.violations:
            print(v)

Stdlib only. Никаких внешних зависимостей.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Stage-aware профили проверок
# ---------------------------------------------------------------------------
#
# У каждой стадии своя структура: Stage 5 = по дням, Stage 4 = по вариантам,
# Stage 0 = по регионам. Жёсткий «±2 H3, ±15% длина» подходит только для
# Stage 5. Для каждой стадии — свой профиль.
#
# Если YAML-поле `stage` определено и совпадает с ключом — берётся
# профиль; иначе используется DEFAULT_PROFILE (Stage 5 совместимость).

# Профиль = TOLERANCE + H2_SYNONYMS + ALLOWED_ADDED_H2 + ALLOWED_REMOVED_H2
# + h2_prefix_match (Stage 0: «Region universe (18)» ≡ «Region universe»).

# Поля YAML, значение которых ДОЛЖНО совпадать дословно (общее для всех стадий).
PRESERVE_FIELDS = (
    "trip_id",
    "stage",
    "duration_nights",
    "chosen_variant",
    "total_budget_rub",
    "budget_target_rub",
    "todo_verification_items",
)

# Stage 5 — финальный план (дни, бюджет, TODO).
_PROFILE_STAGE5 = {
    "tolerance": {
        "length_min_ratio":   0.75,
        "length_max_ratio":   1.15,   # +T9 region-маркеры + сводная таблица
        "h2_count_delta":     1,      # +1 (T9c «Регионы маршрута»)
        "h3_day_count_delta": 0,      # дней — ровно
        "h3_other_delta":     2,      # ±2 H3 (мелкие группировки)
        "checkbox_delta":     0,      # TODO-список — не меняем
        "table_count_delta":  1,      # +1 (сводная таблица регионов)
    },
    "h2_synonyms": {
        "TODO для верификации": {"Что проверить перед поездкой"},
        "Чеклист за 2 недели до поездки": {"Чеклист за 2 недели до выезда"},
        "Контекст для следующих стадий": {"О поездке"},
    },
    "allowed_added_h2":   {"Регионы маршрута"},
    "allowed_removed_h2": set(),   # Stage 5 ничего не удаляет, только переименовывает
    "h2_prefix_match":    False,
    "context_removable":  True,    # T6 разрешает удалить «Контекст для следующих стадий»
}

# Stage 4 — варианты маршрута (без дней, без TODO; H2 — варианты + сравнение).
_PROFILE_STAGE4 = {
    "tolerance": {
        "length_min_ratio":   0.75,
        "length_max_ratio":   1.15,
        "h2_count_delta":     1,
        "h3_day_count_delta": 0,
        "h3_other_delta":     2,
        "checkbox_delta":     0,
        "table_count_delta":  1,
    },
    "h2_synonyms": {},
    "allowed_added_h2":   set(),
    "allowed_removed_h2": set(),
    "h2_prefix_match":    False,
    "context_removable":  False,
}

# Stage 0 — региональная витрина (нет дней, нет TODO, много H3 — регионы).
# Polish добавляет [[поездка]] + [[регион]] маркеры (~10 строк) и «Что
# увидишь:» блок per longlist-регион (~7 × ~3 строки = ~21 строка) —
# суммарно прирост ~15-25% по длине. T4 удаляет `## Следующий шаг`.
# H2-имена в Stage 0 часто содержат счётчик в скобках («Region universe
# (18)», «Longlist (7) — для DR Stage 1») — renderer матчит их по
# префиксу, polish может срезать суффикс. Включаем prefix-match.
_PROFILE_STAGE0 = {
    "tolerance": {
        "length_min_ratio":   0.75,
        "length_max_ratio":   1.30,   # T3b «Что увидишь» добавляет
        "h2_count_delta":     1,      # -1 (T4 удалил «Следующий шаг»)
        "h3_day_count_delta": 0,      # дней в Stage 0 нет — оба = 0
        "h3_other_delta":     0,      # H3 — регионы, должны совпадать
        "checkbox_delta":     0,      # checkbox'ов нет
        "table_count_delta":  1,      # содержательных таблиц нет; ±1 запас
    },
    # Stage 0 H2-секции с suffix'ом в скобках или после «—» — polish T5
    # имеет право срезать суффикс, prefix-match их склеит.
    "h2_synonyms": {},
    "allowed_added_h2":   set(),
    # T4 явно требует удалить `## Следующий шаг` (pipeline-жаргон).
    "allowed_removed_h2": {"Следующий шаг"},
    "h2_prefix_match":    True,
    "context_removable":  False,   # Контекст в Stage 0 — содержательная секция
}

# Stage 1 — DR-база отчётов (карточки авторов по 20 полей, сгруппированы
# по регионам). H2 = регионы (`## РЕГИОН N: …, страна`) + META-DIAGNOSTICS
# подсекции. H3 = карточки (`### Карточка N` или `### Карточка N — суффикс`).
#
# Polish:
#   T1 переписывает H1 в человеко-читаемый.
#   T2 вставляет один маркер `[[поездка: …]]` после frontmatter.
#   T3 опц. вставляет `[[карточка: …]]` маркер перед каждой H3 (37+ маркеров).
#   T4 удаляет финальный «**КОНЕЦ STAGE 1.**» и подписи «к Stage 2».
#
# Поэтому: длина растёт от T3 (~37×80 симв), H2 могут содержать кириллицу
# с английской транскрипцией в скобках (prefix-match помогает), H3-карточек
# должно совпадать ровно (drop/добавление карточки — серьёзное нарушение
# integrity DR-базы).
_PROFILE_STAGE1 = {
    "tolerance": {
        "length_min_ratio":   0.90,   # polish минимальный
        "length_max_ratio":   1.20,   # T2 + до 40 маркеров T3
        "h2_count_delta":     1,      # META-DIAGNOSTICS подсекций может ехать на 1
        "h3_day_count_delta": 0,      # дней в Stage 1 нет
        "h3_other_delta":     0,      # H3 = карточки, ровно совпадают
        "checkbox_delta":     0,      # checkbox'ов нет
        "table_count_delta":  1,
    },
    "h2_synonyms":        {},
    "allowed_added_h2":   set(),
    # Polish T9 удаляет `## WARNINGs` из body (warnings консолидированы
    # в YAML.meta_diagnostics_warnings, секция в body дублирует).
    "allowed_removed_h2": {"WARNINGs", "WARNINGS", "Warnings"},
    "h2_prefix_match":    True,       # «РЕГИОН 1: Сием-Рип (Siem Reap), Камбоджа»
    "context_removable":  False,
}

# Stage 2 — similarity-фильтр авторов. H2: Контекст / Распределение /
# Warnings / Reading list / UNSCORED / Полная таблица / Per-author scoring.
# H3: внутри Reading list (Обязательные/OUTLIER/Расширенный) и Per-author
# (MEDIUM/LOW). Содержательные таблицы — распределение + полная таблица.
#
# Polish:
#   T1 переписывает H1 в человеко-читаемый (без «Stage 2 v…»).
#   T2 вставляет один маркер `[[поездка: …]]` после frontmatter (обложка).
#   T3 удаляет pipeline-жаргон («Следующий шаг», подписи «к Stage 3»).
#   Числа распределения / контрибуции / категории / URL НЕ трогает.
#
# Поэтому: длина почти не меняется (±маркер, −жаргон); H2 фиксированы;
# H3-групп может стать меньше, если категория пуста (HIGH=0 → секция
# может схлопнуться) — допускаем дельту 2.
_PROFILE_STAGE2 = {
    "tolerance": {
        "length_min_ratio":   0.88,
        "length_max_ratio":   1.12,   # T2 добавляет маркер, T1 переписывает H1
        "h2_count_delta":     1,      # -1 (T3 убрал «Следующий шаг»)
        "h3_day_count_delta": 0,      # дней нет
        "h3_other_delta":     2,      # reading-list/per-author группы могут схлопнуться
        "checkbox_delta":     0,      # checkbox'ов нет
        "table_count_delta":  1,      # распределение + полная таблица; ±1 запас
    },
    "h2_synonyms":        {},
    "allowed_added_h2":   set(),
    # Spec §11 «Следующий шаг» — pipeline-жаргон, polish имеет право убрать.
    "allowed_removed_h2": {"Следующий шаг", "Следующий шаг (Stage 3)"},
    "h2_prefix_match":    True,        # «Reading list для Stage 3» ≡ «Reading list»
    "context_removable":  False,       # Контекст — содержательная секция
}

_PROFILE_STAGE3 = {
    "tolerance": {
        "length_min_ratio":   0.90,   # polish минимально режет (убрать
                                       # «Stage 3 v2 …», «Следующий шаг»)
        "length_max_ratio":   1.15,   # polish может добавить маркер
                                       # [[поездка: …]] на обложке, синонимы
        "h2_count_delta":     1,      # допускаем 1 H2 разницу (например,
                                       # если polish конвертирует Контекст)
        "h3_day_count_delta": 0,      # дней нет
        "h3_other_delta":     1,      # регионы (H3) должны совпадать,
                                       # +1 на edge case переименования
        "checkbox_delta":     0,
        "table_count_delta":  1,      # распределение по категориям может
                                       # эволюционировать (+1 строка-Total)
    },
    "h2_synonyms":        {
        # Канон: «Полная агрегация POI» — допускаются альтернативы
        "Полная агрегация POI": {"Агрегация POI", "Все POI"},
        "Распределение по категориям": {"Распределение", "Сводка категорий"},
    },
    # Polish ИМЕЕТ ПРАВО удалить служебные секции (pipeline-жаргон).
    "allowed_removed_h2": {
        "Следующий шаг", "Что дальше", "Source matrix",
    },
    "allowed_added_h2":   set(),
    "h2_prefix_match":    False,
    "context_removable":  False,
}

# Stage 6 — финал (доводка устаканенного 5_vX). Артефакт `6_final.md`:
# `## Координаты маршрута` (таблица точек + порядок + рёбра), `## Дорожное
# досье` (H3: визы/медицина/страховка/этикет/упаковка/экстренное/связь),
# опц. `## Бронирования` / `## Углубления`. Дней (`### День N`) нет — Stage 6
# их НЕ повторяет (механический рендер 5_vX на экспорте).
#
# Polish (см. `references/stage6/stage6-polish-prompt.md`): T1 человекочитаемый
# H1, T2 русификация англицизмов, T3 снятие pipeline-жаргона. Координаты
# (числа/таблица), факты досье и брони — НЕ трогает. Поэтому: длина почти не
# меняется, H2 фиксированы (± опц. секции), таблицы (координаты + контакты)
# совпадают ± запас.
_PROFILE_STAGE6 = {
    "tolerance": {
        "length_min_ratio":   0.85,
        "length_max_ratio":   1.15,
        "h2_count_delta":     1,      # опц. Бронирования/Углубления могут уехать
        "h3_day_count_delta": 0,      # дней в Stage 6 нет — оба = 0
        "h3_other_delta":     2,      # подсекции досье/углублений ± группировка
        "checkbox_delta":     0,      # упаковочные чеклисты — не трогаем
        "table_count_delta":  1,      # координаты + контакты; ±1 запас
    },
    "h2_synonyms":        {},
    "allowed_added_h2":   set(),
    "allowed_removed_h2": {"Следующий шаг", "Что дальше"},
    "h2_prefix_match":    False,
    "context_removable":  False,
}

STAGE_PROFILES: dict[str, dict] = {
    "0_scope":           _PROFILE_STAGE0,
    "1_dr_reports":      _PROFILE_STAGE1,
    "2_similarity":      _PROFILE_STAGE2,
    "3_poi_aggregation": _PROFILE_STAGE3,
    "4_variants":        _PROFILE_STAGE4,
    "5_final_plan":      _PROFILE_STAGE5,
    "6_final":           _PROFILE_STAGE6,
}

# Default-профиль для случая, когда `stage` не определена в YAML.
# Stage 5 — наиболее старый и консервативный, безопасный fallback.
DEFAULT_PROFILE = _PROFILE_STAGE5


# Лидирующая цифра stage → канонический профиль (толерантно к `stage: 0` /
# `stage: 5  # финал` / `5_final_plan`).
_DIGIT_TO_PROFILE = {
    "0": "0_scope", "1": "1_dr_reports", "2": "2_similarity",
    "3": "3_poi_aggregation", "4": "4_variants", "5": "5_final_plan",
    "6": "6_final",
}


def _profile_for(yaml_dict: dict[str, str]) -> dict:
    """Выбрать профиль по YAML-полю `stage` (точное имя или лидирующая цифра).
    Fallback — DEFAULT_PROFILE (см. `_profile_matched` для warning)."""
    stage = str(yaml_dict.get("stage", "")).strip()
    if stage in STAGE_PROFILES:
        return STAGE_PROFILES[stage]
    d = stage[:1]
    if d in _DIGIT_TO_PROFILE:
        return STAGE_PROFILES[_DIGIT_TO_PROFILE[d]]
    return DEFAULT_PROFILE


def _profile_matched(yaml_dict: dict[str, str]) -> bool:
    """Распознан ли `stage` (иначе применён DEFAULT_PROFILE вслепую → warning)."""
    stage = str(yaml_dict.get("stage", "")).strip()
    return stage in STAGE_PROFILES or stage[:1] in _DIGIT_TO_PROFILE


# ---------------------------------------------------------------------------
# Структуры результата
# ---------------------------------------------------------------------------


@dataclass
class CheckReport:
    """Итог проверки. ok=False при любом violation."""
    ok: bool = True
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, int | float | str] = field(default_factory=dict)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.violations.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# ---------------------------------------------------------------------------
# Утилиты разбора
# ---------------------------------------------------------------------------


def _split_yaml_body(text: str) -> tuple[str, str]:
    """Вернуть (yaml_text, body_text). Если frontmatter нет — ("", text).

    Та же защитная нормализация, что у парсера-потребителя: `-{4,}`-делимитер
    → `---` и CRLF→LF. Иначе сырой артефакт (напр. Китай stage 0 с `-----`)
    не распознаётся как frontmatter → polish_check берёт чужой профиль допусков."""
    text = re.sub(r"(?m)^-{4,}[ \t]*$", "---", text.replace("\r\n", "\n"))
    if not text.startswith("---\n"):
        return "", text
    rest = text[4:]
    m = re.search(r"^---[ \t]*$", rest, re.MULTILINE)
    if not m:
        return "", text
    return rest[: m.start()], rest[m.end():].lstrip("\n")


def _strip_scalar_comment(val: str) -> str:
    """Срезать inline-комментарий (` # …`) у нецитированного скаляра."""
    v = val.strip()
    if v[:1] in ('"', "'"):
        return v
    return re.split(r"\s#", v, maxsplit=1)[0].strip()


def _parse_yaml_flat(yaml_text: str) -> dict[str, str]:
    """Грубый flat-parser: только top-level `key: value` строки.

    Достаточно для проверки `PRESERVE_FIELDS` — там скалярные значения.
    Блок-списки/маппинги игнорируем (нам они для sanity-check не нужны).
    Ключи с дефисами поддержаны; inline-комментарии срезаются (иначе значение
    `stage: 5  # финал` не совпало бы с ожидаемым)."""
    out: dict[str, str] = {}
    for line in yaml_text.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.+?)\s*$", line)
        if m:
            out[m.group(1)] = _strip_scalar_comment(m.group(2))
    return out


def _count_headers(body: str, level: int) -> list[str]:
    """Список заголовков уровня `level` в порядке появления."""
    pat = re.compile(rf"^{'#' * level}\s+(.+?)\s*$", re.MULTILINE)
    return [m.group(1) for m in pat.finditer(body)]


def _count_day_headers(body: str) -> int:
    """H3-заголовки вида `### День N ...`."""
    return len(re.findall(r"^###\s+День\s+\d+", body, re.MULTILINE))


def _count_checkboxes(body: str) -> int:
    """Markdown-checkbox пункты `- [ ] ...` / `- [x] ...`."""
    return len(re.findall(r"^\s*-\s+\[[ xX]\]\s+", body, re.MULTILINE))


def _count_tables(body: str) -> int:
    """GFM-таблицы — count delimiter-строк `|---|---|...`."""
    return len(re.findall(r"^\s*\|?\s*[-:]+\s*(?:\|\s*[-:]+\s*)+\|?\s*$", body, re.MULTILINE))


def _h2_prefix(name: str) -> str:
    """Нормализовать H2 к «префиксу до счётчика / суффикса».

    `Region universe (18)` → `Region universe`.
    `Longlist (7) — для DR Stage 1` → `Longlist`.
    `Маршрут по дням` → `Маршрут по дням` (без изменений).

    Используется при `h2_prefix_match: True` в профиле (Stage 0).
    """
    # Срезаем `(...)` count'еры и хвост после ` — `, оставляя смысловой префикс.
    base = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    base = re.split(r"\s+—\s+", base, maxsplit=1)[0].strip()
    return base


def _h2_set_normalized(headers: list[str], profile: dict) -> set[str]:
    """Нормализованное множество H2-имён с учётом synonyms и prefix-match.

    profile["h2_synonyms"] — карта канон → синонимы (двусторонняя).
    profile["h2_prefix_match"] — если True, дополнительно добавляем
        префикс-форму (Stage 0: «Region universe (18)» → «Region universe»).
    """
    syns_map: dict[str, set[str]] = profile.get("h2_synonyms", {}) or {}
    prefix_match = profile.get("h2_prefix_match", False)
    out: set[str] = set()
    for h in headers:
        # При prefix-match сравниваем ТОЛЬКО по префиксу (до счётчика/суффикса).
        # Иначе suffix-only переименование заголовка даёт ложные missing/added:
        # Stage 1 T4 «КАРТОЧКА 2 (multi-region: Пекин + Сиань)» →
        # «КАРТОЧКА 2 (Пекин + Сиань)» и «КАРТОЧКА 29 (user_added, B1 awd.ru)» →
        # «КАРТОЧКА 29» — префиксы совпадают (номер карточки уникален), а полные
        # формы различаются. Добавляя обе формы, старый код ловил полную как
        # missing/added. Префикс-формы достаточно: реальное удаление/переименование
        # самого префикса по-прежнему ловится.
        out.add(_h2_prefix(h) if prefix_match else h)
        for canon, syns in syns_map.items():
            if h in syns:
                out.add(canon)
            elif h == canon:
                out.update(syns)
    return out


# ---------------------------------------------------------------------------
# Главная проверка
# ---------------------------------------------------------------------------


def check_polish(source: str, polished: str) -> CheckReport:
    """Сравнить polished версию с оригиналом, вернуть отчёт.

    Выбирает stage-профиль по YAML-полю `stage` (см. STAGE_PROFILES).
    Если поле не определено — DEFAULT_PROFILE (Stage 5).
    """
    report = CheckReport()

    # 0. Stage-aware профиль (по `stage` из YAML).
    src_yaml, src_body = _split_yaml_body(source)
    pol_yaml, pol_body = _split_yaml_body(polished)
    src_fm = _parse_yaml_flat(src_yaml)
    pol_fm = _parse_yaml_flat(pol_yaml)
    profile = _profile_for(src_fm)
    if not _profile_matched(src_fm):
        report.warn(
            f"stage {src_fm.get('stage')!r} не распознан — применён DEFAULT_PROFILE "
            f"(stage 5); допуски могут не подходить. Проверь поле `stage` в YAML.")
    tolerance = profile["tolerance"]
    report.metrics["stage"] = src_fm.get("stage", "<unknown>")

    # 1. Длина.
    len_src, len_pol = len(source), len(polished)
    ratio = len_pol / max(len_src, 1)
    report.metrics["source_length"] = len_src
    report.metrics["polished_length"] = len_pol
    report.metrics["length_ratio"] = round(ratio, 3)
    if ratio < tolerance["length_min_ratio"]:
        report.fail(
            f"polished короче допустимого: {ratio:.0%} от source "
            f"(минимум {tolerance['length_min_ratio']:.0%}). "
            "Скорее всего полиш дропнул контент."
        )
    elif ratio > tolerance["length_max_ratio"]:
        report.fail(
            f"polished длиннее допустимого: {ratio:.0%} от source "
            f"(максимум {tolerance['length_max_ratio']:.0%}). "
            "Скорее всего полиш дописал свой контент."
        )

    # 2. YAML preserved fields.
    for fld in PRESERVE_FIELDS:
        sv = src_fm.get(fld)
        pv = pol_fm.get(fld)
        if sv is None:
            continue
        if pv is None:
            report.fail(f"YAML-поле `{fld}` пропало после polish (было: {sv!r})")
        elif sv != pv:
            report.fail(
                f"YAML-поле `{fld}` изменено: было {sv!r}, стало {pv!r}"
            )

    # 3. H2 count + содержимое (с учётом synonyms / prefix-match / allowed).
    src_h2 = _count_headers(src_body, 2)
    pol_h2 = _count_headers(pol_body, 2)
    report.metrics["source_h2_count"] = len(src_h2)
    report.metrics["polished_h2_count"] = len(pol_h2)
    if abs(len(pol_h2) - len(src_h2)) > tolerance["h2_count_delta"]:
        report.fail(
            f"H2-секций: source={len(src_h2)}, polished={len(pol_h2)} "
            f"(допуск ±{tolerance['h2_count_delta']}). "
            f"Source: {src_h2}; Polished: {pol_h2}"
        )
    # Пропавшие H2 (с учётом переименования / префиксов / разрешённых удалений).
    src_set = _h2_set_normalized(src_h2, profile)
    pol_set = _h2_set_normalized(pol_h2, profile)
    missing = src_set - pol_set
    allowed_removed = profile.get("allowed_removed_h2", set())
    context_removable = profile.get("context_removable", False)
    context_aliases = (profile.get("h2_synonyms", {})
                       .get("Контекст для следующих стадий", set())
                       | {"Контекст для следующих стадий"})
    for h in missing:
        if h in allowed_removed:
            report.warn(f"H2 «{h}» удалён polish'ом — допустимо (профиль stage)")
        elif context_removable and h in context_aliases:
            report.warn(f"H2 «{h}» удалён polish'ом — допустимо (T6)")
        else:
            report.fail(f"H2 «{h}» отсутствует в polished версии")
    # Неожиданно ДОБАВЛЕННЫЕ H2. Обе стороны через _h2_set_normalized —
    # иначе при prefix-match суффикс-переименование (Stage 1 T4) даёт ложный
    # «добавлен»: raw-форма `КАРТОЧКА 2 (Пекин)` не входит в нормализованный
    # src_set (там префикс `КАРТОЧКА 2`). Симметрично с `missing` выше.
    allowed_added = profile.get("allowed_added_h2", set())
    added = pol_set - src_set
    for h in added:
        if h in allowed_added:
            report.warn(f"H2 «{h}» добавлен polish'ом — допустимо (профиль stage)")
        else:
            report.fail(
                f"H2 «{h}» добавлен polish'ом, но не входит в разрешённые "
                f"({sorted(allowed_added) or '∅'}) — polish не должен выдумывать секции"
            )
    # Дубли одноимённых H2: set-диф выше их схлопывает и НЕ ловит удаление одного
    # из двух одинаковых заголовков. Multiset-сверка сырых имён закрывает это.
    src_counts, pol_counts = Counter(src_h2), Counter(pol_h2)
    for name, cnt in src_counts.items():
        if cnt > 1 and pol_counts[name] < cnt and name not in allowed_removed:
            report.fail(
                f"H2 «{name}»: было {cnt} экземпляров, стало {pol_counts[name]} — "
                f"потеряна дублирующая секция (polish не должен ронять дубли)")

    # 4. H3 День N count — критично для маршрута Stage 5.
    src_days = _count_day_headers(src_body)
    pol_days = _count_day_headers(pol_body)
    report.metrics["source_day_count"] = src_days
    report.metrics["polished_day_count"] = pol_days
    if abs(pol_days - src_days) > tolerance["h3_day_count_delta"]:
        report.fail(
            f"Дней в маршруте: source={src_days}, polished={pol_days} "
            "— расхождение недопустимо"
        )

    # 5. H3 в целом (для Stage 0 — регионы; для Stage 5 — Деньги/SIM/etc.).
    src_h3 = _count_headers(src_body, 3)
    pol_h3 = _count_headers(pol_body, 3)
    other_src = len(src_h3) - src_days
    other_pol = len(pol_h3) - pol_days
    report.metrics["source_h3_other"] = other_src
    report.metrics["polished_h3_other"] = other_pol
    if abs(other_pol - other_src) > tolerance["h3_other_delta"]:
        report.fail(
            f"H3-подсекций (кроме дней): source={other_src}, polished={other_pol} "
            f"— расхождение > ±{tolerance['h3_other_delta']}"
        )

    # 6. Checkboxes (TODO + чеклист) — релевантно для Stage 5.
    src_cb = _count_checkboxes(src_body)
    pol_cb = _count_checkboxes(pol_body)
    report.metrics["source_checkboxes"] = src_cb
    report.metrics["polished_checkboxes"] = pol_cb
    if abs(pol_cb - src_cb) > tolerance["checkbox_delta"]:
        report.fail(
            f"TODO/checklist пунктов: source={src_cb}, polished={pol_cb} "
            "— polish не должен менять checkbox-список"
        )

    # 7. Таблицы.
    src_tab = _count_tables(src_body)
    pol_tab = _count_tables(pol_body)
    report.metrics["source_tables"] = src_tab
    report.metrics["polished_tables"] = pol_tab
    if abs(pol_tab - src_tab) > tolerance["table_count_delta"]:
        report.fail(
            f"Таблиц: source={src_tab}, polished={pol_tab} — недопустимо"
        )

    # 8. Бюджет «Углублений» (Stage 6).
    for name, viol in check_enrichment_budget(pol_body):
        report.fail(viol)
    report.metrics["enrichment_blocks"] = len(_enrichment_blocks(pol_body))

    return report


# ---------------------------------------------------------------------------
# Бюджет «Углублений» (Stage 6)
# ---------------------------------------------------------------------------

# Дорожный документ читают с телефона в пути. Блок длиннее этого не дочитывают,
# а лишние предложения — ровно то место, где модель добирает объём вымыслом:
# фактуры на дальний посёлок мало, а тон остаётся уверенным.
# Ограничение стоит ЗДЕСЬ, а не только в каноне, сознательно: инструкция
# «сохранить polished.md» в том же каноне есть и систематически пропускается,
# поэтому бюджет обязан быть гейтом, а не пожеланием.
ENRICHMENT_MAX_SENTENCES = 5
# Строку источника снимаем ЦЕЛИКОМ, вместе с URL: если оставить хвост ссылки,
# последняя точка текста перестаёт быть концом текста, и счётчик теряет
# предложение (блок из шести проходил как пятипредложенный).
_SOURCE_LINE_RE = re.compile(r"^[ \t]*(?:источник|источники|source)\s*[:—-].*$",
                             re.I | re.M)
# Точка/!/? как конец предложения. Сокращения с точкой («ок. 1010 г.», «в т.ч.»)
# дали бы ложные срабатывания, поэтому требуем пробел+заглавную либо конец строки.
_SENTENCE_END_RE = re.compile(r"[.!?…](?=\s+[«\"(]?[A-ZА-ЯЁ]|\s*$)")


def _enrichment_blocks(body: str) -> list[tuple[str, str]]:
    """H3-блоки внутри `## Углубления` → [(заголовок, тело)]. Вне секции — пусто."""
    m = re.search(r"^##\s+Углубления\s*$(.*?)(?=^##\s|\Z)", body,
                  re.M | re.S)
    if not m:
        return []
    out: list[tuple[str, str]] = []
    for blk in re.finditer(r"^###\s+(.+?)\s*$(.*?)(?=^###\s|\Z)", m.group(1),
                           re.M | re.S):
        out.append((blk.group(1).strip(), blk.group(2)))
    return out


def check_enrichment_budget(body: str, *,
                            max_sentences: int = ENRICHMENT_MAX_SENTENCES
                            ) -> list[tuple[str, str]]:
    """Проверить бюджет и провенанс блоков «Углублений».

    → список (заголовок, текст нарушения). Пустой список = всё в норме.
    Секции нет — нарушений нет: enrichment опционален (stage6-final §6.5).
    """
    out: list[tuple[str, str]] = []
    for title, raw in _enrichment_blocks(body):
        has_source = bool(_SOURCE_LINE_RE.search(raw))
        # Строку источника из подсчёта предложений исключаем: она служебная и
        # не должна съедать бюджет содержания.
        prose = _SOURCE_LINE_RE.sub("", raw)
        prose = re.sub(r"^\s*[-*]\s*$", "", prose, flags=re.M).strip()
        n = len(_SENTENCE_END_RE.findall(prose))
        if n > max_sentences:
            out.append((title, f"«Углубления → {title}»: {n} предложений при "
                               f"лимите {max_sentences}. Дорожный документ читают "
                               f"с телефона; длинную справку — в отдельный файл "
                               f"(внешние_справки/)."))
        if not has_source:
            out.append((title, f"«Углубления → {title}»: нет строки источника. "
                               f"Историческая справка без источника непроверяема — "
                               f"добавь «Источник: …» или убери блок."))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_report(report: CheckReport) -> str:
    """Человеко-читаемый отчёт."""
    lines: list[str] = []
    status = "OK" if report.ok else "FAIL"
    lines.append(f"polish_check: {status}")
    lines.append("")
    lines.append("Метрики:")
    for k, v in report.metrics.items():
        lines.append(f"  {k}: {v}")
    if report.warnings:
        lines.append("")
        lines.append("Предупреждения:")
        for w in report.warnings:
            lines.append(f"  ⚠ {w}")
    if report.violations:
        lines.append("")
        lines.append("Нарушения:")
        for v in report.violations:
            lines.append(f"  ✗ {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="polish_check.py",
        description="Sanity-checker для polish-step Stage 5 (см. stage5-polish-prompt.md)",
    )
    p.add_argument("--source", required=True, help="оригинальный *.md файл стадии")
    p.add_argument("--polished", required=True, help="отполированный *.md файл")
    p.add_argument("--json", action="store_true",
                   help="вывести отчёт как JSON в stdout (для chat-интеграции)")
    args = p.parse_args(argv)

    src = Path(args.source).read_text(encoding="utf-8")
    pol = Path(args.polished).read_text(encoding="utf-8")
    report = check_polish(src, pol)

    if args.json:
        import json
        payload = {
            "ok": report.ok,
            "violations": report.violations,
            "warnings": report.warnings,
            "metrics": report.metrics,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_format_report(report))

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())

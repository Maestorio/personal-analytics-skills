"""adapter.py — адаптация распарсенного содержимого под получателя.

Принцип (export-design.md §3, §7):
  - Один и тот же артефакт стадии может рендериться под разных получателей
    (self / parents / партнёр / гид / ...).
  - Для каждого получателя есть generic strip-rules, общие для всех
    стадий: «убрать TODO», «убрать warnings», «убрать «План реагирования
    на риски» секцию».
  - Stage-специфичные правила (например, «для родителей в Stage 5 убрать
    `_log` блоки внутри дней») — добавляются stage-модулями в Steps 2+
    через расширение реестра.

Engine-уровень даёт:
  - `adapt_for_recipient(parsed, recipient)` — главная функция.
  - `RECIPIENT_RULES` — реестр правил.
  - `register_stage_extension(recipient, stage, fn)` — точка расширения
    для stage-модулей.

Адаптер НЕ модифицирует входной dict — возвращает новый.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Правила адаптации
# ---------------------------------------------------------------------------


@dataclass
class RecipientRules:
    """Generic-правила для одного получателя.

    Поля:
      - `strip_sections` — точные заголовки top-level (H2) секций, которые
        целиком выкидываются из дерева секций и из body. Сравнение
        case-sensitive по точному совпадению.
      - `strip_subsections` — заголовки H3+, которые выкидываются из всех
        родительских секций. Например, «План реагирования на риски»
        иногда живёт как H3 внутри другой секции.
      - `strip_inline_patterns` — список regex; каждое совпадение удаляется
        из body (используется по строке). Например, чтобы убрать
        TODO-маркеры из тела параграфа.
      - `strip_yaml_fields` — поля frontmatter, которые не показываются
        в выходе (warnings, internal diagnostics).
      - `keep_only_yaml_fields` — если задан, оставить только эти ключи
        в frontmatter; остальные выкинуть. Имеет приоритет над
        `strip_yaml_fields`.
      - `strip_warnings_block` — если True, выкинуть секцию warnings
        целиком + поле `warnings` из frontmatter.
      - `strip_todo_markers` — если True, удалить inline TODO-маркеры
        (`TODO:`, `(TODO)`, `<TODO>`) из всех body-секций.
    """
    strip_sections: set[str] = field(default_factory=set)
    strip_subsections: set[str] = field(default_factory=set)
    strip_inline_patterns: list[re.Pattern] = field(default_factory=list)
    strip_yaml_fields: set[str] = field(default_factory=set)
    keep_only_yaml_fields: set[str] | None = None
    strip_warnings_block: bool = False
    strip_todo_markers: bool = False


# Реестр generic recipient-правил.
#
# v1: `self` — пользователь сам, ничего не выкидываем (для верификации
# TODO/warnings нужно видеть). `parents` — sanitized версия для родителей
# (см. export-design.md §3).
RECIPIENT_RULES: dict[str, RecipientRules] = {
    "self": RecipientRules(
        # Self видит всё. Только internal-диагностики из YAML убираем.
        strip_yaml_fields={"_log", "_diagnostic"},
    ),
    "field": RecipientRules(
        # Полевая версия (in-trip): исключаем подготовительные и review-секции.
        # Оставляем дни, карты, сводные таблицы, гастрономию и ПЛАН РИСКОВ
        # (он нужен именно в поле). Глубокий рационал «Логика ключевых решений»
        # живёт внутри «Контекст…» и отсекается на уровне рендера (build_pdf
        # рисует приложение «Обоснование…» только для self). См.
        # export-design.md §"Pre-trip vs in-trip" / travel-plan-review §III.
        strip_sections={
            "Шапка",
            "Критические подготовительные пункты",
            "Чеклист за 2 недели до поездки",
            "TODO для верификации",
            "Diff с предыдущим планом",
            "Honest assessment",
        },
        strip_yaml_fields={"_log", "_diagnostic"},
    ),
    "parents": RecipientRules(
        # Родителям не нужны TODO / warnings / risks-таблица / "Контекст
        # для следующих стадий" / user_comments stage 3 / tag_parse_warnings.
        # См. export-design.md §3 «v2 — родители».
        strip_sections={
            "Контекст для следующих стадий",
            "План реагирования на риски",
            "TODO для верификации",
            "Honest assessment",
            "Diff с предыдущим планом",
        },
        strip_subsections={
            "TODO",
            "Warnings",
            "Tag parse warnings",
            "Risk-таблица",
            "Swap-стратегии",
        },
        strip_inline_patterns=[
            # Inline `⚠️ Риски` блоки в днях — для родителей убираем.
            re.compile(r"^⚠️\s*Риски.*?(?=\n\n|\Z)", re.MULTILINE | re.DOTALL),
        ],
        strip_warnings_block=True,
        strip_todo_markers=True,
        # Сохраняем только metadata, релевантную родителям.
        keep_only_yaml_fields={
            "trip_id", "stage", "duration_nights", "created",
            "chosen_variant", "total_budget_rub",
        },
    ),
}


# Stage-специфичные extension-функции.
# Ключ: (recipient, stage_id), например ("parents", "5_final_plan").
# Значение: функция (parsed_copy: dict) -> None, мутирующая dict in place.
# Регистрируется stage-модулями в Steps 2+.
_STAGE_EXTENSIONS: dict[tuple[str, str], list[Callable[[dict], None]]] = {}


def register_stage_extension(
    recipient: str, stage_id: str, fn: Callable[[dict], None]
) -> None:
    """Зарегистрировать stage-специфичное правило для получателя.

    Вызывается stage-модулями (Steps 2+) на import-time. `fn` получает
    уже generic-обработанный dict и может мутировать его in place.
    """
    _STAGE_EXTENSIONS.setdefault((recipient, stage_id), []).append(fn)


# ---------------------------------------------------------------------------
# Главная функция адаптации
# ---------------------------------------------------------------------------


def adapt_for_recipient(parsed: dict, recipient: str) -> dict:
    """Применить правила адаптации к распарсенному содержимому.

    Возвращает НОВЫЙ dict — оригинал не модифицируется. Если получатель
    не зарегистрирован — кидает KeyError (явный fail-fast: лучше падать
    громко, чем рендерить с дефолтом, который не подходит).
    """
    if recipient not in RECIPIENT_RULES:
        raise KeyError(
            f"неизвестный recipient {recipient!r}; зарегистрированы: "
            f"{sorted(RECIPIENT_RULES.keys())}"
        )
    rules = RECIPIENT_RULES[recipient]
    out = copy.deepcopy(parsed)

    _apply_yaml_rules(out, rules)
    _apply_section_rules(out, rules)
    _apply_inline_rules(out, rules)

    # Нормализация stage: digit-only YAML (`stage: 0`) парсится как int → str,
    # чтобы routing/registry/extensions (ключи вида "0_scope") не промахивались,
    # а `if 0` не глотал нулевую стадию.
    if out.get("stage") is not None:
        out["stage"] = str(out["stage"])

    # Stage-специфичные расширения (если зарегистрированы).
    stage_id = out.get("stage")
    if stage_id is not None:
        for fn in _STAGE_EXTENSIONS.get((recipient, stage_id), []):
            fn(out)

    return out


# ---------------------------------------------------------------------------
# Внутренние шаги адаптации
# ---------------------------------------------------------------------------


def _apply_yaml_rules(out: dict, rules: RecipientRules) -> None:
    """Применить strip/keep к frontmatter."""
    fm = out.get("frontmatter") or {}
    if rules.keep_only_yaml_fields is not None:
        fm = {k: v for k, v in fm.items() if k in rules.keep_only_yaml_fields}
    else:
        for k in rules.strip_yaml_fields:
            fm.pop(k, None)
    if rules.strip_warnings_block:
        fm.pop("warnings", None)
        fm.pop("tag_parse_warnings", None)
    out["frontmatter"] = fm


def _apply_section_rules(out: dict, rules: RecipientRules) -> None:
    """Выкинуть запрещённые секции из дерева."""
    sections = out.get("sections") or []
    out["sections"] = [
        _filter_section(s, rules)
        for s in sections
        if s["heading"] not in rules.strip_sections
        and not (rules.strip_warnings_block and _is_warnings_section(s["heading"]))
    ]


def _filter_section(section: dict, rules: RecipientRules) -> dict:
    """Рекурсивно отфильтровать subsections."""
    section = dict(section)
    subs = section.get("subsections") or []
    section["subsections"] = [
        _filter_section(s, rules)
        for s in subs
        if s["heading"] not in rules.strip_subsections
        and not (rules.strip_warnings_block and _is_warnings_section(s["heading"]))
    ]
    return section


def _is_warnings_section(heading: str) -> bool:
    """Эвристика: секция про warnings (русский / английский варианты)."""
    h = heading.lower().strip()
    return h in {"warnings", "предупреждения", "tag parse warnings", "тег-предупреждения"}


# Маркеры TODO разных форматов — `TODO:`, `(TODO)`, `<TODO ...>`, `TODO для верификации`.
_TODO_RE = re.compile(
    r"(?:\(TODO[^)]*\)|<TODO[^>]*>|\bTODO\b[:\s].*?)(?=\n|$)",
    re.IGNORECASE,
)


def _apply_inline_rules(out: dict, rules: RecipientRules) -> None:
    """Применить inline regex-strip ко всем body-секциям."""
    if not rules.strip_inline_patterns and not rules.strip_todo_markers:
        return
    for s in out.get("sections") or []:
        _strip_inline_in_section(s, rules)


def _strip_inline_in_section(section: dict, rules: RecipientRules) -> None:
    body = section.get("body", "") or ""
    for pat in rules.strip_inline_patterns:
        body = pat.sub("", body)
    if rules.strip_todo_markers:
        body = _TODO_RE.sub("", body)
    section["body"] = body
    for sub in section.get("subsections") or []:
        _strip_inline_in_section(sub, rules)


# ---------------------------------------------------------------------------
# Удобные хелперы
# ---------------------------------------------------------------------------


def list_recipients() -> list[str]:
    """Список зарегистрированных получателей."""
    return sorted(RECIPIENT_RULES.keys())


def register_recipient(name: str, rules: RecipientRules) -> None:
    """Зарегистрировать нового получателя.

    Используется, когда добавляется поддержка partner / guide / archive
    (см. export-design.md §3 «TBD modes») — пишется в stage-модуле или
    в дополнительном файле, не в этом adapter.py.
    """
    RECIPIENT_RULES[name] = rules

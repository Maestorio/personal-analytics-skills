#!/usr/bin/env python3
"""taxonomy.py — словарь таксонов travel-planning (SSOT переводов).

Единый источник истины для отображаемых ярлыков таксономии: категории
авторов / POI, роли регионов, severity предупреждений, тональности,
компоненты similarity. Данные — в соседнем `data/taxonomy.json`; этот модуль
даёт к ним типовой доступ.

Назначение (Фаза 1 русификации):
  • `.md`-артефакты и JSON-контракты скриптов остаются с **английскими**
    каноническими ключами — машинный слой не меняется.
  • Парсеры экспорта принимают ярлыки **на любом языке** (`pattern()` +
    `canon()`), но внутри кода живут только канонические EN-ключи.
  • Рендер экспорта печатает ярлыки через `label()` → видимый вывод русский.

Stdlib-only (как остальные скрипты пакета). API:
  load()                       — кэшированное чтение taxonomy.json
  label(group, key, lang=None) — канонический ключ → отображаемый ярлык
  canon(group, text)           — ярлык ЛЮБОГО языка/алиаса → канонический ключ
  pattern(group)               — regex-альтернация всех ярлыков (для парсеров)
  localize_terms(group, text)  — EN-формы терминов в свободном тексте → ярлыки
  localize_labels(group, text) — то же, но только в позиции лида (`Tempo:`)
  keys(group) / groups()       — перечисление ключей / групп
  no_translate()               — список непереводимых терминов (POI и т.п.)

Канонический ключ группы = текущий машинный EN-ключ (тот же, что в YAML и
в константах скриптов: `CATEGORY_RANK`, `VALID_AUTHOR_CATEGORIES` и пр.).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent / "data" / "taxonomy.json"

_CACHE: Optional[dict] = None
_REV_CACHE: dict[str, dict[str, str]] = {}
_PAT_CACHE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------

def load() -> dict:
    """Кэшированное чтение `data/taxonomy.json`."""
    global _CACHE
    if _CACHE is None:
        with _DATA_PATH.open(encoding="utf-8") as fh:
            _CACHE = json.load(fh)
    return _CACHE


def _terms() -> dict:
    return load()["terms"]


def _group(group: str) -> dict:
    """Группа терминов по имени; понятная ошибка при неизвестной группе."""
    terms = _terms()
    if group not in terms:
        raise ValueError(
            f"taxonomy: неизвестная группа '{group}'. "
            f"Доступны: {', '.join(sorted(terms))}"
        )
    return terms[group]


# ---------------------------------------------------------------------------
# Нормализация (для обратного резолва)
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """trim · casefold · ё→е · '_'→' ' · схлопывание пробелов.

    Делает `STRONG_CONFIRMED`, `STRONG CONFIRMED`, `strong   confirmed`
    эквивалентными при обратном резолве.
    """
    s = str(text).strip().casefold().replace("ё", "е").replace("_", " ")
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------------------
# Прямой резолв: ключ → ярлык
# ---------------------------------------------------------------------------

def default_lang() -> str:
    return load().get("default_display_lang", "en")


def label(group: str, key: str, lang: Optional[str] = None) -> str:
    """Канонический ключ → отображаемый ярлык на `lang`.

    `lang=None` → `default_display_lang` (ru). Если `key` пришёл не в
    канонической форме (например, уже EN/RU-ярлык) — резолвится через
    `canon()`. Неизвестный ключ возвращается как есть (рендер не падает).
    """
    terms = _group(group)
    if lang is None:
        lang = default_lang()
    entry = terms.get(key)
    if entry is None:
        ck = canon(group, key)
        entry = terms.get(ck) if ck else None
        if entry is None:
            return key
    return entry.get(lang) or entry.get("en") or key


def short_label(group: str, key: str) -> str:
    """Короткая форма ярлыка (`ru_short`), fallback на `label()`.

    Для узких колонок/метров (например, `independence` → «самост.» вместо
    «самостоятельность»). Если у записи нет `ru_short` — обычный `label()`.
    """
    terms = _group(group)
    entry = terms.get(key)
    if entry is None:
        ck = canon(group, key)
        entry = terms.get(ck) if ck else None
    if entry and entry.get("ru_short"):
        return entry["ru_short"]
    return label(group, key)


# ---------------------------------------------------------------------------
# Обратный резолв: ярлык любого языка → канонический ключ
# ---------------------------------------------------------------------------

def _forms(entry: dict) -> list:
    """Все отображаемые формы записи термина (без канонического ключа)."""
    forms = [entry.get("en"), entry.get("ru")]
    forms += entry.get("aliases_ru", [])
    forms += entry.get("aliases_en", [])
    return [f for f in forms if f]


def _reverse(group: str) -> dict[str, str]:
    """Карта нормализованный-ярлык → канонический ключ (кэш).

    Включает сам канонический ключ, EN/RU-значения и алиасы. Коллизия
    (один нормализованный ярлык → два разных ключа внутри группы) —
    ошибка данных, поднимаем ValueError.
    """
    if group in _REV_CACHE:
        return _REV_CACHE[group]
    rev: dict[str, str] = {}
    for key, entry in _group(group).items():
        for form in [key, *_forms(entry)]:
            n = _norm(form)
            if not n:
                continue
            if n in rev and rev[n] != key:
                raise ValueError(
                    f"taxonomy: коллизия reverse-map в группе '{group}': "
                    f"'{form}' резолвится и в '{rev[n]}', и в '{key}'"
                )
            rev[n] = key
    _REV_CACHE[group] = rev
    return rev


def canon(group: str, text: Optional[str]) -> Optional[str]:
    """Ярлык на любом языке/алиасе → канонический EN-ключ (или None).

    Резолв только внутри указанной группы (кросс-групповой запрещён).
    """
    if text is None:
        return None
    n = _norm(text)
    if not n:
        return None
    return _reverse(group).get(n)


# ---------------------------------------------------------------------------
# Регулярка-альтернация для парсеров
# ---------------------------------------------------------------------------

def pattern(group: str) -> str:
    """Non-capturing альтернация ВСЕХ ярлыков группы (все языки + алиасы).

    Длинные варианты раньше коротких (`СЛАБЫЙ СИГНАЛ` до `СЛАБЫЙ`), чтобы
    жадная альтернация не отрезала хвост. Возвращает `(?:a|b|c)` — каждый
    ярлык экранирован; вставляется как под-выражение в регулярки парсеров.
    """
    if group in _PAT_CACHE:
        return _PAT_CACHE[group]
    forms: set[str] = set()
    for entry in _group(group).values():
        forms.update(_forms(entry))
    ordered = sorted(forms, key=lambda s: (-len(s), s))
    alt = "|".join(re.escape(s) for s in ordered)
    pat = f"(?:{alt})"
    _PAT_CACHE[group] = pat
    return pat


# ---------------------------------------------------------------------------
# Локализация свободного текста (EN-формы → ярлыки)
# ---------------------------------------------------------------------------

# Разделители внутри составного термина взаимозаменяемы: `mid-range`,
# `mid range`, `mid_range` — одно и то же.
_SEP = r"[ _-]"


def _form_regex(form: str) -> str:
    """Форма термина → regex, толерантный к разделителям. Пустая форма → ''."""
    parts = [re.escape(p) for p in re.split(r"[ _-]+", form.strip()) if p]
    return (r"\b" + _SEP.join(parts) + r"\b") if parts else ""


def _en_rules(group: str) -> list:
    """(EN-форма, канонический ключ) для группы; длинные формы раньше коротких.

    Только EN-формы (сам ключ + `en` + `aliases_en`): RU-ярлыки уже на целевом
    языке, их подменять нечем. Порядок важен: `mid-range independent` должен
    сработать раньше `mid-range`, иначе короткий термин отрежет хвост.
    """
    rules: list = []
    for key, entry in _group(group).items():
        forms = {key}
        for f in [entry.get("en"), *entry.get("aliases_en", [])]:
            if f:
                forms.add(f)
        rules += [(f, key) for f in forms]
    rules.sort(key=lambda r: (-len(r[0]), r[0]))
    return rules


def _localize(group: str, text: Optional[str], lang: Optional[str],
              lookahead: str) -> str:
    """Общий движок `localize_terms` / `localize_labels`."""
    if not text:
        return text or ""
    out = text
    for form, key in _en_rules(group):
        rx = _form_regex(form)
        if not rx:
            continue
        repl = label(group, key, lang)
        out = re.sub(rx + lookahead, lambda _m, r=repl: r, out, flags=re.IGNORECASE)
    return out


def localize_terms(group: str, text: Optional[str], lang: Optional[str] = None) -> str:
    """Свободный текст: EN-формы терминов группы → ярлыки на `lang`.

    Для полей, которые модель/DR пишут прозой, а не enum'ом («Стиль
    путешествия: backpacker / mid-range independent»). Неизвестные слова не
    трогаются, повторный проход ничего не меняет (идемпотентно).
    """
    return _localize(group, text, lang, "")


def localize_labels(group: str, text: Optional[str], lang: Optional[str] = None) -> str:
    """То же, но ТОЛЬКО в позиции лида — перед двоеточием (`**Tempo:**`).

    Отдельно от `localize_terms`, потому что короткие слова-лейблы (`Country`,
    `Math`) в свободной прозе значат не то же самое, что в позиции метки, и
    слепая подмена ломала бы текст.
    """
    return _localize(group, text, lang, r"(?=\*{0,2}\s*:)")


# ---------------------------------------------------------------------------
# Перечисление
# ---------------------------------------------------------------------------

def keys(group: str) -> list:
    return list(_group(group).keys())


def groups() -> list:
    return list(_terms().keys())


def no_translate() -> list:
    return list(load().get("no_translate", []))


def legend(*group_names: str, sep: str = " · ", eq: str = " = ") -> str:
    """Строка-легенда соответствия RU↔EN по указанным группам.

    Нужна в экспорте (Р2): `.md`-артефакт остаётся с EN-таксонами, видимый
    вывод — русский, легенда даёт читателю карту обратно. Дубли (один и тот
    же RU=EN из разных групп, напр. CONTESTED в poi_category и badge)
    схлопываются; пары, где RU==EN, пропускаются."""
    seen: set = set()
    parts: list = []
    for g in group_names:
        for k in keys(g):
            ru = label(g, k, "ru")
            en = label(g, k, "en")
            if ru == en or (ru, en) in seen:
                continue
            seen.add((ru, en))
            parts.append(f"{ru}{eq}{en}")
    return sep.join(parts)


if __name__ == "__main__":  # pragma: no cover — ручная проверка
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "label":
        print(label(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None))
    elif len(sys.argv) >= 3 and sys.argv[1] == "canon":
        print(canon(sys.argv[2], sys.argv[3]))
    elif len(sys.argv) >= 2 and sys.argv[1] == "pattern":
        print(pattern(sys.argv[2]))
    else:
        print("groups:", ", ".join(groups()))

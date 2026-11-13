"""cover_common.py — единый «паспорт поездки» для шапок всех стадий.

Принцип (2026-06-01): таблица ключевых параметров на обложке любой стадии
начинается с общего блока «паспорт поездки» в фиксированном порядке и с
едиными метками, затем идёт стадийный блок (свой на каждой стадии).

Порядок паспорта:
  Кто едет → Регионы/Маршрут → Сезон → Длительность → Темп → Бюджет

Каждая стадия передаёт только те значения, что у неё есть и релевантны
(на ранних стадиях темп/бюджет обычно опускаются — деньги и темп
становятся важны ближе к Stage 4/5). Метка географии настраивается
(`geo_label`): «Регионы» / «Страны» / «Старт / финиш» / «Маршрут».

Модуль stdlib-only.
"""
from __future__ import annotations

import re
from pathlib import Path

# taxonomy — словарь таксонов (scripts/taxonomy.py). Здесь — группа `tempo`
# (значения темпа на обложке); переводы живут только в taxonomy.json.
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import taxonomy


# Имена, где в имени файла ё пишется через е (файлы избегают ё). Восстанавливаем
# ё в видимом имени на обложке. Расширять по мере появления участников.
_YO_NAMES = {
    "мария": "Мария", "мария": "Мария", "артем": "Артём", "артём": "Артём",
    "семен": "Семён", "петр": "Пётр", "федор": "Фёдор", "тема": "Тёма",
}


def _cap_name(part: str) -> str:
    """Капитализировать одно имя участника + восстановить ё по словарю."""
    p = part.strip()
    if not p:
        return p
    return _YO_NAMES.get(p.lower(), p[:1].upper() + p[1:])


def profile_name(profile_path: str | None) -> str | None:
    """`profiles/алексей.md` → `Алексей`; `profiles/алексей_мария.md` →
    `Алексей и Мария`. Каждое имя с заглавной, ё восстанавливается по словарю
    (раньше капитализировалась только первая буква всей строки → «и мария»)."""
    if not profile_path:
        return None
    stem = Path(str(profile_path)).stem.strip()
    parts = [p for p in stem.split("_") if p]
    return " и ".join(_cap_name(p) for p in parts) or None


# Квалификаторы стороны света в trip_id → прилагательное (муж. / жен. род).
_GEO_QUALIFIERS = {
    "север":       ("Северный", "Северная"),
    "юг":          ("Южный", "Южная"),
    "запад":       ("Западный", "Западная"),
    "восток":      ("Восточный", "Восточная"),
    "центр":       ("Центральный", "Центральная"),
    "центральный": ("Центральный", "Центральная"),
}


# Не-географические токены trip_id: обозначения группы («китай_родители_2027»)
# — часть имени поездки, но не место; в гео-строке обложки их печатать нельзя
# («Китай · Родители» читалось как две страны). Имена участников — через
# ключи _YO_NAMES + частые формы.
_NON_GEO_TOKENS = ({"родители", "семья", "друзья", "дети", "пара", "соло"}
                   | {k for k in _YO_NAMES})


def is_non_geo_token(part: str) -> bool:
    """Токен trip_id — обозначение группы/участника, не география."""
    return part.strip().lower() in _NON_GEO_TOKENS


def _trip_geo_parts(trip_id: str | None) -> list[str]:
    """Части trip_id без хвостовой даты (`_YYYY-MM` / `_YYYY`) и без
    группа-токенов (`родители`, имена участников)."""
    out: list[str] = []
    for p in str(trip_id or "").split("_"):
        if re.fullmatch(r"\d{4}(?:-\d{2})?", p):
            break
        if p and not is_non_geo_token(p):
            out.append(p)
    return out


def humanize_trip_geo(
    trip_id: str | None, *, join: str = " и ", default: str = "Поездка",
) -> str:
    """trip_id → человекочитаемая гео-строка для обложки.

    `вьетнам_север_2026-09` → «Северный Вьетнам»: квалификатор стороны света
    становится прилагательным с согласованием по роду страны (эвристика по
    окончанию: `-а`/`-я` → жен.), а не «Вьетнам + Север». Несколько стран без
    квалификатора склеиваются через `join` («Камбоджа и Лаос»).
    """
    parts = _trip_geo_parts(trip_id)
    if not parts:
        return default
    quals = [p for p in parts if p.lower() in _GEO_QUALIFIERS]
    countries = [p for p in parts if p.lower() not in _GEO_QUALIFIERS]
    if len(quals) == 1 and len(countries) == 1:
        country = countries[0][:1].upper() + countries[0][1:]
        adj_m, adj_f = _GEO_QUALIFIERS[quals[0].lower()]
        fem = country.lower().endswith(("а", "я"))
        return f"{adj_f if fem else adj_m} {country}"
    return join.join(p[:1].upper() + p[1:] for p in parts) or default


def _ok(v: object) -> bool:
    s = str(v).strip() if v is not None else ""
    return bool(s) and s != "—"


# Нормализация темпа к русскому (англ. коды приходят из YAML/контекста).
# Пары EN-форма → русский ярлык строятся из taxonomy-группы `tempo`
# (SSOT переводов — taxonomy.json; алиасы moderate/fast/rapid — там же).
def _tempo_ru_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in taxonomy.keys("tempo"):
        ru = taxonomy.label("tempo", key)
        entry = taxonomy.load()["terms"]["tempo"][key]
        for form in [entry["en"], *entry.get("aliases_en", [])]:
            pairs.append((form, ru))
    return pairs


_TEMPO_RU = dict(_tempo_ru_pairs())


_TEMPO_WORDS = (set(_TEMPO_RU)
                | {v.lower() for v in _TEMPO_RU.values()}
                | {"медленный", "умеренный", "быстрый", "размеренн", "сбалансир", "активн"})


def looks_like_tempo(s: str | None) -> bool:
    """Похоже ли значение на темп (а не случайный токен вроде «и»).

    Защита от ложных срабатываний контекст-регэкспов («темпе и транспорте»
    → «и»): принимаем только если строка содержит известный токен темпа.
    """
    if not s:
        return False
    low = str(s).lower()
    return any(w in low for w in _TEMPO_WORDS)


def localize_tempo(tempo: str | None) -> str | None:
    """`balanced` → `сбалансированный`; уже-русское/смешанное — как есть.

    Заменяет англ. токен темпа в любом месте строки (`balanced (3.6 ночи/база)`
    → `сбалансированный (3.6 ночи/база)`), регистронезависимо.
    """
    if not tempo:
        return tempo
    out = str(tempo)
    for en, ru in _TEMPO_RU.items():
        out = re.sub(rf"\b{en}\b", ru, out, flags=re.IGNORECASE)
    return out


def passport_rows(
    *,
    who: str | None = None,
    geo: str | None = None,
    geo_label: str = "Регионы",
    season: str | None = None,
    duration: str | None = None,
    tempo: str | None = None,
    budget: str | None = None,
) -> list[tuple[str, str]]:
    """Строки паспорта поездки в едином порядке/метках (пустые опускаются)."""
    rows: list[tuple[str, str]] = []
    if _ok(who):
        rows.append(("Кто едет", str(who)))
    if _ok(geo):
        rows.append((geo_label, str(geo)))
    if _ok(season):
        rows.append(("Сезон", str(season)))
    if _ok(duration):
        rows.append(("Длительность", str(duration)))
    if _ok(tempo):
        rows.append(("Темп", str(localize_tempo(tempo))))
    if _ok(budget):
        rows.append(("Бюджет", str(budget)))
    return rows


# Хвост-ссылка на внутренний референс скилла в warning/info-тексте — источник
# читателю недоступен и не нужен («…такие места были бы LOW SIGNAL. См.
# stage3-poi.md §6.5.»). Общий для Stage 2 и Stage 3 (одна природа warnings).
_INTERNAL_REF_RE = re.compile(
    r"\s*(?:См\.|see)\s+stage\S*\.md(\s*§?[\d.]+)?\.?", re.IGNORECASE)


def strip_internal_refs(text: str) -> str:
    """Срезать хвост-ссылку на внутренний stage-референс из видимого текста."""
    if not text:
        return text
    return _INTERNAL_REF_RE.sub("", text).rstrip()

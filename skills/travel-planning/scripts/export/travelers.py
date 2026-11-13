"""travelers.py — единый резолвер «Кто едет» для обложек экспорта.

До этого модуля у каждой стадии была своя логика (Stage 0/1/4 — только текст
polish-маркера; Stage 2 — маркер + разбор имени файла профиля; Stage 3/5/6 —
только разбор имени файла профиля) — расхождения между стадиями на одной
и той же поездке. `resolve_travelers` — единая цепочка источников (первый
непустой побеждает):

  1. Профиль: `yaml["travelers_profile"]` → файл `profiles/{stem}.md`,
     поле frontmatter `display_name` (заполняется в Profile mode).
  2. `trip.yaml` рядом со стадийным артефактом: `travelers: [...]` — список
     имён, join « и », каждое имя капитализировано (+ восстановление «ё»
     по словарю `cover_common._YO_NAMES`, как в разборе имени файла профиля).
  3. Polish-маркер `[[поездка: группа: … ]]` (или `кто: …` — у Stage 2 другой
     ключ) — текст как есть.
  4. Разбор имени файла профиля (`алексей_родители` → «Алексей и Родители»).

Пути поиска (шаги 1–2): `input_path` — один путь ИЛИ список путей. Экспорт
передаёт [исходный md, файл вывода]: polished-md эфемерен и часто лежит вне
`trips/{trip_id}/` (Р9 — polish не сохраняется в trips/), тогда как вывод
идёт в каноническую директорию поездки — оттуда `trip.yaml` и `profiles/`
находятся. `profiles/` ищется walk-up'ом (до 4 уровней вверх от директории
каждого пути), а не фиксированной глубиной — устойчиво и к канону
`{travel_root}/trips/{trip_id}/`, и к запуску на файле в произвольном месте
рядом со скопированным деревом.

Каждый шаг graceful: отсутствие файла/поля — не ошибка, просто следующий
источник цепочки. `input_path=None` (например, юнит-тест на голом dict) —
шаги 1–2 пропускаются, работает только маркер/имя-профиля.
"""
from __future__ import annotations

from pathlib import Path

if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cover_common  # type: ignore[no-redef]
    import parser as _parser  # type: ignore[no-redef]
else:
    from . import cover_common
    from . import parser as _parser

# Сколько уровней вверх подниматься в поиске profiles/ от директории пути.
# Канон — 2 (`trips/{trip_id}/` → `trips/` → `{travel_root}`); 4 — запас на
# нестандартную вложенность, не сканируя весь диск.
_WALK_UP_LEVELS = 4


def _candidate_dirs(paths) -> list[Path]:
    """Нормализовать вход (путь | список путей | None) в список директорий."""
    if paths is None:
        raw = []
    elif isinstance(paths, (str, Path)):
        raw = [paths]
    else:
        raw = list(paths)
    out: list[Path] = []
    for p in raw:
        if not p:
            continue
        try:
            d = Path(p).resolve().parent
        except OSError:
            continue
        if d not in out:
            out.append(d)
    return out


def _find_profile_path(travelers_profile: str, dirs: list[Path]) -> Path | None:
    """Найти файл профиля walk-up'ом: от каждой директории вверх до
    `_WALK_UP_LEVELS`, проверяя `profiles/{stem}.md`."""
    fname = Path(str(travelers_profile)).name
    for d in dirs:
        cur = d
        for _ in range(_WALK_UP_LEVELS):
            cand = cur / "profiles" / fname
            try:
                if cand.exists():
                    return cand
            except OSError:
                break
            if cur.parent == cur:
                break
            cur = cur.parent
    return None


def _read_profile_display_name(travelers_profile: str | None,
                               dirs: list[Path]) -> str | None:
    """`display_name` из frontmatter файла профиля (Р10, profile-management.md §7.1)."""
    if not travelers_profile or not dirs:
        return None
    profile_path = _find_profile_path(travelers_profile, dirs)
    if profile_path is None:
        return None
    try:
        parsed = _parser.parse_stage_file(profile_path)
    except OSError:
        return None
    name = parsed.get("frontmatter", {}).get("display_name")
    if not name:
        return None
    name = str(name).strip()
    return name or None


def _read_trip_yaml_travelers(dirs: list[Path]) -> str | None:
    """`travelers:` из `trip.yaml` рядом с одним из путей → строка."""
    for d in dirs:
        trip_yaml = d / "trip.yaml"
        try:
            if not trip_yaml.exists():
                continue
            text = trip_yaml.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _warnings = _parser.parse_yaml(text)
        names = fm.get("travelers")
        if not isinstance(names, list) or not names:
            continue
        parts = [str(n).strip() for n in names if str(n).strip()]
        if parts:
            return " и ".join(cover_common._cap_name(p) for p in parts)
    return None


def resolve_travelers(yaml: dict | None, trip_marker: dict | None,
                      input_path=None) -> str:
    """Единый резолвер «Кто едет» — первый непустой источник побеждает.

    `yaml` — frontmatter стадийного артефакта (для `travelers_profile`);
    `trip_marker` — dict из `_parse_trip_marker(body)` (`[[поездка: …]]`);
    `input_path` — путь к стадийному артефакту ИЛИ список путей-кандидатов
    (обычно [исходный md, файл вывода] — см. докстринг модуля); без него
    работают только шаги 3–4.
    """
    yaml = yaml or {}
    trip_marker = trip_marker or {}
    prof = yaml.get("travelers_profile")
    dirs = _candidate_dirs(input_path)

    display_name = _read_profile_display_name(prof, dirs)
    if display_name:
        return display_name

    from_trip_yaml = _read_trip_yaml_travelers(dirs)
    if from_trip_yaml:
        return from_trip_yaml

    marker_who = trip_marker.get("группа") or trip_marker.get("кто")
    if marker_who:
        return str(marker_who).strip()

    return cover_common.profile_name(prof) or ""


def replace_profile_stem(text: str | None, yaml: dict | None, who: str | None) -> str:
    """Заменить сырой стем профиля в видимой прозе на резолвнутое имя.

    Стадии пишут в контекст «группа `алексей_родители` (пара 60–61…)» —
    машинный идентификатор в user-facing тексте. Если резолвер дал имя
    («Родители») — подменяем и обратённый в код стем (`` `стем` ``), и голый.
    Без профиля/имени текст не трогается.
    """
    if not text:
        return text or ""
    prof = (yaml or {}).get("travelers_profile")
    if not prof or not who:
        return text
    stem = Path(str(prof)).stem
    if not stem or stem == who:
        return text
    return text.replace(f"`{stem}`", who).replace(stem, who)

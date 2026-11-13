"""stages/stage0.py — экстрактор контента + PDF builder для Stage 0.

Stage 0 — региональное сужение (longlist 6–8 регионов для DR Stage 1).
PDF (self) — landscape A4, **презентационная витрина regions**: cover-hero,
карточки регионов сгруппированы по role (Core/Supporting/Niche/Borderline)
в 2-колоночную сетку. Каждая карточка — кликабельный заголовок ведёт на
Google Images по имени региона.

Структура PDF (landscape A4):
  1. Hero-обложка (полноразмерная плашка в primary с заголовком +
     подзаголовком; ниже — таблица ключевых параметров поездки).
  2. Контекст для следующих стадий (прозой) + tempo/math summary.
  3. Карточки longlist'а, сгруппированы по role (Core → Supporting →
     Niche → Borderline). 2-колоночная сетка. Reserve-пара помечается
     side-badge «RESERVE → {парный регион}».
  4. Excluded regions — компактные definition-list строки.
  5. Non-canonical found — info-box за элемент со статусом
     (in_longlist / excluded).
  6. Tempo + country quota — компактная data_table.
  7. Honest assessment — прозой, section_bar заголовок.

Все визуальные блоки — из pdf_lib.entity_card / card_grid /
hero_cover_block / section_bar (см. pdf-visual-language.md §10).
Stage-модуль только извлекает контент и мапит региональные поля
на универсальные слоты entity_card (title/badge/meta/body/side_badges).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

# Импорт соседних модулей пакета — поддерживаем оба режима запуска.
if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from export import adapter as _adapter   # type: ignore[no-redef]
    from export import pdf_lib                # type: ignore[no-redef]
    from export import renderer as _renderer  # type: ignore[no-redef]
    from export import cover_common            # type: ignore[no-redef]
    from export import travelers as _travelers  # type: ignore[no-redef]
    from export.style import COLORS, ROLE_BADGES   # type: ignore[no-redef]
else:
    from .. import adapter as _adapter
    from .. import pdf_lib
    from .. import renderer as _renderer
    from .. import cover_common
    from .. import travelers as _travelers
    from ..style import COLORS, ROLE_BADGES

# taxonomy — словарь таксонов (scripts/taxonomy.py, на уровень выше export/).
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import taxonomy


# ---------------------------------------------------------------------------
# Известные имена секций (Stage 0 артефакт)
# ---------------------------------------------------------------------------

_CONTEXT_H2 = "Контекст для следующих стадий"
_UNIVERSE_H2_PREFIX = "Region universe"     # «Region universe (18)»
_LONGLIST_H2_PREFIX = "Longlist"            # «Longlist (7) — для DR Stage 1»
_EXCLUDED_H2 = "Excluded regions"
_NON_CANONICAL_H2_PREFIX = "Non-canonical"  # «Non-canonical found»
# «Темп и распределение по странам» (канон Фазы 2b) / легаси «Tempo + country
# quota» — секция-якорь ищется по обоим языкам, иначе тихо пропадает из экспорта.
_TEMPO_H2_PREFIX = ("Темп", "Tempo")
_HONEST_H2 = "Honest assessment"
_SKIP_H2 = {"Следующий шаг"}                # pipeline-жаргон, не для презентации


# Месяца для season-инференции из trip_id.
_MONTHS_RU = {
    "01": "январь", "02": "февраль", "03": "март", "04": "апрель",
    "05": "май", "06": "июнь", "07": "июль", "08": "август",
    "09": "сентябрь", "10": "октябрь", "11": "ноябрь", "12": "декабрь",
}


# ---------------------------------------------------------------------------
# Маркеры от polish
# ---------------------------------------------------------------------------

# `[[поездка: …]]` маркер — общий со Stage 4: ключевые параметры обложки.
_TRIP_MARKER_RE = re.compile(r"\[\[\s*поездка:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)

# `[[регион: имя | role: core | density: HIGH | сезон: ok | ночи: 3-5]]` —
# Stage 0 специфичный маркер. Polish T3 вставляет его перед каждым `### {регион}`
# в Longlist, чтобы PDF-builder имел канонический источник role-классификации,
# не завися от legacy-формата (КЛТ_1 universe сгруппирован по странам, role
# в YAML отсутствует).
_REGION_MARKER_RE = re.compile(r"\[\[\s*регион:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)


def _parse_marker_kv(s: str) -> dict:
    """Распарсить `k: v | k: v` (как в `[[поездка: …]]`)."""
    out: dict = {}
    for part in s.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _parse_trip_marker(body: str) -> dict:
    """`[[поездка: …]]` → dict ключевых параметров поездки (для обложки)."""
    if not body:
        return {}
    m = _TRIP_MARKER_RE.search(body)
    return _parse_marker_kv(m.group(1)) if m else {}


def _parse_region_markers(body: str) -> dict[str, dict]:
    """`[[регион: имя | role: …]]` → dict[region_name] = {role, density, сезон, ночи}.

    Возвращает карту по имени региона (lowercase для устойчивости к регистру).
    Если маркер встречается несколько раз для одного имени — берётся первый.
    """
    if not body:
        return {}
    out: dict[str, dict] = {}
    for m in _REGION_MARKER_RE.finditer(body):
        kv = _parse_marker_kv(m.group(1))
        name = kv.pop("имя", None) or kv.pop("name", None)
        if not name:
            continue
        out.setdefault(name.strip().lower(), kv)
    return out


# ---------------------------------------------------------------------------
# Role inference (fallback для legacy формата)
# ---------------------------------------------------------------------------

# Канонические role-значения, которые рендерим в карточках. Любой не-known
# value нормализуется через `_normalize_role` к ближайшему известному.
_KNOWN_ROLES = {"core", "supporting", "niche", "borderline"}


def _normalize_role(value: str | None) -> str | None:
    """Нормализовать пользовательский role-string к ключу из ROLE_BADGES.

    Принимает русский/английский, регистронезависимо. Неизвестное → None.
    """
    if not value:
        return None
    v = value.strip().lower()
    aliases = {
        "core":         "core",
        "ядро":         "core",
        "ядерный":      "core",
        "supporting":   "supporting",
        "поддерживающий": "supporting",
        "вспомогательный": "supporting",
        "supp":         "supporting",
        "niche":        "niche",
        "нишевый":      "niche",
        "borderline":   "borderline",
        "пограничный":  "borderline",
    }
    if v in aliases:
        return aliases[v]
    if v in _KNOWN_ROLES:
        return v
    # Двуязычный fallback через taxonomy (покрывает канонические RU-термины
    # «Ядро/Поддержка/Нишевый/Пограничный», которых нет в aliases выше).
    key = (taxonomy.canon("region_role", value)
           or taxonomy.canon("region_role_group", value))
    return key.lower() if key and key.lower() in _KNOWN_ROLES else None


def _infer_role_from_longlist_item(item: dict) -> str:
    """Fallback role-инференция, когда ни polish-маркер, ни YAML `role:` не дают значения.

    Эвристика (для КЛТ_1-подобных legacy артефактов без `role:` в YAML):
      • `reserve_for` задан → "supporting" (это substitute, не core);
      • density HIGH без reserve_for → "core";
      • density MED без reserve_for → "core" (must-кандидат типа Пномпеня);
      • density LOW → "niche";
      • иначе → "supporting".

    «MED без reserve → core» — компромисс под legacy: в КЛТ_1 Пномпень (MED)
    декларирован «core» в reasoning, но это не отражено в YAML. Лучше отнести
    MED-без-reserve к core, чем разделить must-кандидата на supporting.
    Для нового артефакта polish даёт role явно через `[[регион: …]]`.
    """
    if item.get("reserve_for"):
        return "supporting"
    density = (item.get("density_tag") or "").upper()
    if density in ("HIGH", "MED"):
        return "core"
    if density == "LOW":
        return "niche"
    return "supporting"


def _resolve_role(item: dict, region_marker: dict | None) -> str:
    """Финальная role: polish-маркер → YAML `role` → инференция."""
    if region_marker:
        r = _normalize_role(region_marker.get("role"))
        if r:
            return r
    r = _normalize_role(item.get("role"))
    if r:
        return r
    return _infer_role_from_longlist_item(item)


# ---------------------------------------------------------------------------
# Cleanup: убрать pipeline-жаргон из видимого текста (контекст / honest)
# ---------------------------------------------------------------------------
#
# Сырой 0_scope.md (без polish) содержит инлайн-ссылки на YAML-поля
# (`home_eq_start: true`, `retrospective: true`, `trip_id: …`) и
# скобочные пояснения с теми же полями. Для presentation-PDF это шум.
# Polish T5 должен их убирать, но мы хотим, чтобы PDF выглядел чисто
# и без polish — иначе показывать пользователю сырой технический
# артефакт.

# YAML-ish field reference: `field` или `field_name` (lowercase + опц.
# underscores) — может быть snake_case (`home_eq_start`) или одним словом
# (`retrospective`). Когда такое появляется в backtick'ах с `: value` после
# — это явный YAML-жаргон.
_YAML_FIELDISH = r"[a-z][a-z0-9_]*\s*[:=]\s*[^`)]+"

# 1. ` (\`field: value\`) ` / ` (\`field\`)` — скобочная ссылка с backtick'ом.
_RX_PAREN_BACKTICK = re.compile(rf"\s*\(\s*`{_YAML_FIELDISH}`\s*\)")
# 2. ` \`field: value\` ` — голый backtick'нутый YAML-ref без скобок.
_RX_BARE_BACKTICK = re.compile(rf"\s*`{_YAML_FIELDISH}`")
# 3. Bullet «Флаг \`field: value\` — …» — целый bullet про YAML-флаг
#    (с continuation-строками, обычно indented пробелами после переноса).
_RX_FLAG_BULLET = re.compile(
    r"^\s*-\s*Флаг\s+`[a-z][a-z0-9_]*[^`]*`[^\n]*(?:\n[ \t]+[^\n]*)*\n?",
    re.MULTILINE,
)
# 4. trip_id в quoted-form `вьетнам_2023-09` — это конкретный идентификатор
#    поездки, тоже жаргон для пользователя; backtick-обёртка + дата в конце.
_RX_TRIP_ID = re.compile(r"\s*`[а-яa-z_]+_\d{4}-\d{2}`")


def _strip_yaml_jargon(text: str) -> str:
    """Удалить из видимого текста YAML-ссылки и pipeline-жаргон.

    Применяется к context/honest/tempo prose — не к карточкам регионов
    (там и так выжимка). Polish T5 должен делать то же самое, но скрипт
    делает это безусловно — на случай рендера без polish.
    """
    if not text:
        return text
    out = text
    out = _RX_FLAG_BULLET.sub("", out)
    out = _RX_PAREN_BACKTICK.sub("", out)
    out = _RX_BARE_BACKTICK.sub("", out)
    out = _RX_TRIP_ID.sub("", out)
    # Двойные пробелы / пробелы перед «.» «,» «;» после вырезов.
    out = re.sub(r"\s+([.,;])", r"\1", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _ru_prose(text: str) -> str:
    """Остаточные EN-термины видимой прозы Stage 0 → русские (taxonomy SSOT).

    Два разных случая, поэтому два механизма:
      • лиды секции «Темп и распределение» (`**Tempo:** balanced`) — только в
        позиции метки: `Country`/`Math` в свободной фразе значат не то же
        самое, слепая подмена ломала бы текст;
      • scope-формат в тексте (`explicit_list` → «явный список») — в любом
        месте, включая backtick'и. YAML-поле `trip_format` не трогается.
    """
    if not text:
        return text
    out = taxonomy.localize_labels("scope_labels", text)
    return taxonomy.localize_terms("scope_format", out)


def _prose(text: str) -> str:
    """Единая подготовка видимой прозы (контекст / темп / honest) для ОБЕИХ
    веток рендера: чистка pipeline-жаргона + русские лейблы и термины."""
    return _ru_prose(_strip_yaml_jargon(text))


# ---------------------------------------------------------------------------
# Body description extraction
# ---------------------------------------------------------------------------

# Регекспы для отделения "differentiator" от технических key-value строк
# Опц. лид строки: bullet-маркер `- `/`• ` и/или markdown-bold `**` обёртка
# (polish часто даёт технические метки как `- **Состав:** …`). Без учёта этого
# префикса `in_wts`-блок «Что увидишь» не закрывался и поглощал все строки
# карточки → слишком высокая карточка → LayoutError.
_LIST_BOLD_LEAD = r"(?:[-•*]\s*)?\*{0,2}\s*"
# longlist-описания. Технические метки выкидываем, остальное идёт в card body.
_TECH_KEY_LINE_RE = re.compile(
    r"^\s*" + _LIST_BOLD_LEAD +
    r"(?:состав|ночи|релевантность профилю|сезон в [^:]+|логистика|"
    r"туристическая нагрузка|ограничения|density|плотность|role|роль|"
    r"reserve binding)"
    r"\s*\*{0,2}\s*[:.]", re.IGNORECASE,
)
_PRINCIPLE_LINE_RE = re.compile(
    r"^\s*" + _LIST_BOLD_LEAD + r"принципиально\s*\*{0,2}\s*[:.]?\s*(.+)$", re.IGNORECASE)
_NON_CANON_LINE_RE = re.compile(
    r"^\s*" + _LIST_BOLD_LEAD + r"non-canonical\s*\*{0,2}\s*[:.]?\s*(.+)$", re.IGNORECASE)
# «Что увидишь:» (polish T8) — наиболее предпочтительный body карточки.
# Содержит 3-5 ключевых впечатлений конкретных достопримечательностей.
# Если строка есть — приоритет над «Принципиально:».
# Контент после маркера опционален (`(.*)`): polish может дать
# `**Что увидишь:**` отдельной строкой и список bullet'ами ниже.
_WHAT_TO_SEE_RE = re.compile(
    r"^\s*\*?\*?что\s+увид[еи]шь\*?\*?\s*[:.]?\s*(.*)$", re.IGNORECASE,
)
# Markdown-bold обёртка может занять весь блок: `**Что увидишь:** ...`.
_WHAT_TO_SEE_MD_BOLD_RE = re.compile(
    r"^\s*\*\*что\s+увидишь:?\*\*\s*(.*)$", re.IGNORECASE,
)
# Сезон-маркер: «Сезон в феврале 2026: ok» / «risk» / «bad/blocked».
_SEASON_LINE_RE = re.compile(
    r"^\s*сезон\s+в\s+[^:]+:\s*(.+)$", re.IGNORECASE,
)


def _split_lines_keep_blanks(text: str) -> list[str]:
    return text.splitlines()


def _find_subsection(sections: list, h2_prefix: str, h3_name: str) -> dict | None:
    """Найти подсекцию `### h3_name` под H2-заголовком начинающимся с `h2_prefix`.

    Tолерантен к: суффиксу H3 (например, `### Баттамбанг — RESERVE` сматчит
    `Баттамбанг`); регистру; иной группировке H2 (по странам vs по role).
    """
    h3_low = h3_name.strip().lower()
    for sec in sections:
        if not sec["heading"].startswith(h2_prefix):
            continue
        for ss in _all_subsections(sec):
            head = ss["heading"].strip().lower()
            # Точный матч ИЛИ префикс с разделителем («— RESERVE», «(7)»).
            if head == h3_low or head.startswith(h3_low + " ") or head.startswith(h3_low + "—") \
                    or head.startswith(h3_low + " —"):
                return ss
    return None


def _all_subsections(section: dict) -> list[dict]:
    """Рекурсивно собрать все subsections section'а (через все уровни)."""
    out: list[dict] = []
    stack = list(section.get("subsections") or [])
    while stack:
        ss = stack.pop(0)
        out.append(ss)
        stack.extend(ss.get("subsections") or [])
    return out


# Заголовок role-группы в `## Region universe`. Двуязычен: канон Фазы 2b даёт
# `### Ядро поездки (4)`, легаси — `### Core (4) — ядро поездки`. Резолв
# конкретного значения — через `_normalize_role` (обе taxonomy-группы).
_ROLE_HEADING_RE = re.compile(
    rf"^\s*({taxonomy.pattern('region_role_group')}"
    rf"|{taxonomy.pattern('region_role')})\b",
    re.IGNORECASE,
)


def _parse_universe_roles(sections: list) -> dict:
    """`## Region universe` → {имя региона (lower) → role}, ЕСЛИ universe
    сгруппирован по role (H3 = `Core (4)…` / `Supporting…` / `Niche…` /
    `Borderline…`, H4 = регионы). Если universe сгруппирован иначе (например по
    странам, как в КЛТ) — вернётся пусто, и кандидаты уйдут в хвостовую группу.

    Имя кладём и полное, и базовое (без суффикса «— RESERVE» / «(N)»),
    чтобы матч с YAML-именем excluded был устойчив.
    """
    out: dict = {}
    for sec in sections:
        if not (sec.get("heading") or "").startswith(_UNIVERSE_H2_PREFIX):
            continue
        for h3 in (sec.get("subsections") or []):
            m = _ROLE_HEADING_RE.match(h3.get("heading") or "")
            if not m:
                continue
            role = _normalize_role(m.group(1))
            if not role:
                continue
            for reg in (h3.get("subsections") or []):
                full = (reg.get("heading") or "").strip().lower()
                if not full:
                    continue
                out[full] = role
                base = re.split(r"\s+—\s+|\s+\(", full)[0].strip()
                out.setdefault(base, role)
    return out


def _split_what_to_see(text: str) -> list[str]:
    """Разбить «Что увидишь» текст на bullet-точки.

    Разделители (по приоритету):
      1. `\\n- ` / `\\n• ` — markdown-bullets с явными маркерами;
      2. `\\n` — текст уже очищен от markdown-маркеров (приходит из
         `_extract_description_and_season` где `- ` уже срезан) —
         каждая строка = одна точка;
      3. `;` — классический разделитель в «X; Y; Z» строке;
      4. fallback: одна точка = весь текст.
    """
    text = text.strip()
    if not text:
        return []
    lines = re.split(r"\n+", text)
    # 1. Явные bullets — собирать строки начинающиеся с маркера.
    bullets: list[str] = []
    for ln in lines:
        m = re.match(r"^\s*[-•]\s+(.+)$", ln)
        if m:
            bullets.append(m.group(1).strip())
    if len(bullets) >= 2:
        return bullets
    # 2. Многострочный текст: каждая строка — одна или несколько точек.
    #    Дополнительно режем каждую строку по `;` (часто polish даёт
    #    смешанный формат: первая строка с `;` после маркера, остальные —
    #    отдельными строками).
    nl_parts: list[str] = []
    for ln in lines:
        for chunk in ln.split(";"):
            cleaned = chunk.strip(" .;").strip()
            if cleaned:
                nl_parts.append(cleaned)
    if len(nl_parts) >= 2:
        return nl_parts
    # 3. Одна точка — целиком текст.
    return [text]


def _extract_description_and_season(
    body: str,
) -> tuple[str, list[str] | None, str | None, bool]:
    """Из body региона (под `### {регион}`) достать: description, season_note, non_canonical.

    Возвращает: (description, description_bullets, season_note, non_canonical).

    description (приоритет сверху вниз):
      1. «**Что увидишь:** …» — блок от polish T3b с конкретными
         впечатлениями. Это богатое описание (3-5 точек), наиболее
         ценное для карточки. **Дополнительно** разбивается на список
         bullet-точек (`description_bullets`); builder рендерит их
         через bullet-список, а не плоский текст.
      2. «Принципиально: …» — differentiator от исходного Stage 0
         артефакта. Рендерится плоской фразой.
      3. fallback — первые 1-2 не-технические предложения.

    Технические key-value строки (Состав, Ночи, Density, Logистика, …)
    всегда выкидываются.

    season_note — текст после «Сезон в {месяц год}:» (ok / risk / blocked /
    свободная фраза). None если не нашли.

    non_canonical — True, если строка «Non-canonical: …» присутствует.
    """
    if not body:
        return "", None, None, False
    description_lines: list[str] = []
    what_to_see: str | None = None
    principle: str | None = None
    season: str | None = None
    non_canon = False

    # «Что увидишь:» может растянуться на multi-line блок (после T8 — bullets
    # или perечисление через ; ). Соберём всё от строки-маркера до следующего
    # технического ключа / blank line / Принципиально.
    in_wts = False
    wts_lines: list[str] = []
    for raw in _split_lines_keep_blanks(body):
        line = raw.strip()
        if not line:
            if in_wts:
                in_wts = False
                continue
            continue

        # Закрываем «Что увидишь:» блок если встретили технический ключ
        # или другую секцию.
        if in_wts and (_TECH_KEY_LINE_RE.match(line) or _PRINCIPLE_LINE_RE.match(line)
                       or _NON_CANON_LINE_RE.match(line) or _SEASON_LINE_RE.match(line)):
            in_wts = False

        m_wts = _WHAT_TO_SEE_MD_BOLD_RE.match(line) or _WHAT_TO_SEE_RE.match(line)
        if m_wts:
            first = m_wts.group(1).strip()
            if first:
                wts_lines.append(first)
            in_wts = True
            continue
        if in_wts:
            # Multi-line continuation — обычно перечисление через `; ` или
            # bullets `- ...`. Bullets чистим от маркера.
            cleaned = re.sub(r"^[-•]\s+", "", line)
            wts_lines.append(cleaned)
            continue

        m_prin = _PRINCIPLE_LINE_RE.match(line)
        if m_prin:
            principle = m_prin.group(1).strip()
            continue
        m_nc = _NON_CANON_LINE_RE.match(line)
        if m_nc:
            non_canon = True
            continue
        m_season = _SEASON_LINE_RE.match(line)
        if m_season:
            season = m_season.group(1).strip()
            continue
        if _TECH_KEY_LINE_RE.match(line):
            continue
        if len(description_lines) < 2:
            description_lines.append(line)

    # «Что увидишь» собираем сохраняя многострочную структуру —
    # для качественного парсинга bullet'ов (через `\n`).
    if wts_lines:
        what_to_see = "\n".join(wts_lines).strip()

    # Приоритет: «Что увидишь» (polish T3b) → «Принципиально» → fallback.
    bullets: list[str] | None = None
    if what_to_see:
        parts = _split_what_to_see(what_to_see)
        if len(parts) >= 2:
            # 2+ точек — рендерим bullet-списком, description оставляем
            # как fallback-строку (на случай старых вызовов без bullets-поля).
            bullets = [_capitalize_first(p) for p in parts]
            description = "; ".join(parts)
        else:
            description = parts[0] if parts else what_to_see
    elif principle:
        description = principle
    else:
        description = " ".join(description_lines).strip()
    return _capitalize_first(description), bullets, season, non_canon


def _capitalize_first(text: str) -> str:
    """Капитализировать первую букву (пропуская **markdown-bold** и пробелы).

    Источник Stage 0 часто даёт описания после двоеточия со строчной буквы
    («крупнейший ансамбль…»). Для presentation-карточки это выглядит как
    обрезанная фраза. Делаем prose-вид: первая буква заглавная.
    """
    if not text:
        return text
    # Пропускаем ведущие пробелы / `**` / `*` / `_`.
    i = 0
    while i < len(text) and text[i] in " \t*_":
        i += 1
    if i >= len(text):
        return text
    head, ch, tail = text[:i], text[i], text[i + 1:]
    if ch.isalpha() and ch.islower():
        return f"{head}{ch.upper()}{tail}"
    return text


# ---------------------------------------------------------------------------
# Extract content
# ---------------------------------------------------------------------------


@dataclass
class Region:
    name: str
    country: str | None
    density: str            # HIGH/MED/LOW
    role: str               # core/supporting/niche/borderline
    nights_min: int | None
    nights_optimum: int | None
    reserve_for: str | None
    substitute_reason: str | None
    description: str
    description_bullets: list[str] | None    # «Что увидишь» как список точек
    season_note: str | None
    is_non_canonical: bool


@dataclass
class ExcludedRegion:
    name: str
    reason: str
    description: str = ""           # обогащается из ## Region universe
    role: str | None = None        # из role-группировки ## Region universe (если есть)
    description_bullets: list[str] | None = None  # «Что увидишь», если polish дал


@dataclass
class NonCanonical:
    name: str
    interest_match: str
    status: str             # in_longlist / excluded
    reason: str | None


def extract_content(parsed: dict, *, input_path: "Path | None" = None) -> dict:
    """Извлечь структуру для PDF-builder'а из распарсенного 0_scope.md.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10)."""
    fm = parsed.get("frontmatter") or {}
    sections = parsed.get("sections") or []
    body = parsed.get("body") or ""
    trip_params = _parse_trip_marker(body)
    resolved_who = _travelers.resolve_travelers(fm, trip_params, input_path)
    if resolved_who:
        trip_params["группа"] = resolved_who
    region_markers = _parse_region_markers(body)

    # — Longlist —
    longlist: list[Region] = []
    for item in (fm.get("longlist") or []):
        name = item.get("region") or ""
        if not name:
            continue
        marker = region_markers.get(name.strip().lower())
        # Body description: из ## Longlist (primary), fallback на ## Region universe.
        ss = _find_subsection(sections, _LONGLIST_H2_PREFIX, name) \
            or _find_subsection(sections, _UNIVERSE_H2_PREFIX, name)
        desc, bullets, season, non_canon = _extract_description_and_season(
            ss["body"] if ss else "",
        )
        # Маркер от polish'а может явно дать сезон / non-canonical / role.
        if marker:
            if marker.get("сезон"):
                season = marker["сезон"]
            if marker.get("non-canonical") in ("true", "да", "yes"):
                non_canon = True
        longlist.append(Region(
            name=name,
            country=item.get("country"),
            density=(item.get("density_tag") or "").upper(),
            role=_resolve_role(item, marker),
            nights_min=item.get("nights_min"),
            nights_optimum=item.get("nights_optimum"),
            reserve_for=item.get("reserve_for"),
            substitute_reason=item.get("substitute_reason"),
            description=desc,
            description_bullets=bullets,
            season_note=season,
            is_non_canonical=non_canon,
        ))

    # — Excluded regions — primary source: YAML; description / «Что увидишь»
    # обогащаются из ## Region universe, role — из role-группировки universe
    # (для единой «вселенной» с пометкой ✓ в DR / ◌ кандидат на замену).
    role_map = _parse_universe_roles(sections)
    excluded: list[ExcludedRegion] = []
    for item in (fm.get("excluded_regions") or []):
        name = item.get("region") or ""
        ss = _find_subsection(sections, _UNIVERSE_H2_PREFIX, name) \
            or _find_subsection(sections, _EXCLUDED_H2, name)
        desc, bullets, _, _ = _extract_description_and_season(ss["body"] if ss else "")
        excluded.append(ExcludedRegion(
            name=name,
            reason=item.get("reason") or "",
            description=desc or "",
            role=role_map.get(name.strip().lower()),
            description_bullets=bullets,
        ))

    # — Non-canonical found — primary: YAML.
    non_canonical: list[NonCanonical] = []
    for item in (fm.get("non_canonical_regions") or []):
        non_canonical.append(NonCanonical(
            name=item.get("region") or "",
            interest_match=item.get("interest_match") or "",
            status=item.get("status") or "",
            reason=item.get("reason"),
        ))

    # — Контекст / honest / tempo body —
    context_body: str | None = None
    honest_body: str | None = None
    tempo_body: str | None = None
    for sec in sections:
        if sec["heading"] == _CONTEXT_H2:
            context_body = sec["body"]
        elif sec["heading"] == _HONEST_H2:
            honest_body = sec["body"]
        elif sec["heading"].startswith(_TEMPO_H2_PREFIX):
            tempo_body = sec["body"]

    # Сверка YAML longlist ↔ тело: ловит молчаливый дрейф (пропавшие регионы,
    # сдвиг описаний, нарушенный порядок) ДО сборки PDF.
    _val = validate_longlist(parsed)

    return {
        "title":          parsed.get("title"),
        "frontmatter":    fm,
        "trip_params":    trip_params,
        "longlist":       longlist,
        "excluded":       excluded,
        "non_canonical":  non_canonical,
        "context":        context_body,
        "tempo":          tempo_body,
        "honest":         honest_body,
        "warnings":       list(fm.get("warnings") or []) + _val["warnings"],
        "validation_errors": _val["errors"],
    }


def _region_matches(body_name: str, yaml_name: str) -> bool:
    """Толерантный матч имени региона тела ↔ YAML (как в `_find_subsection`)."""
    b = body_name.strip().lower()
    y = yaml_name.strip().lower()
    return (b == y or b.startswith(y + " ") or b.startswith(y + "—")
            or b.startswith(y + " —") or y.startswith(b + " ") or y.startswith(b + "—"))


def validate_longlist(parsed: dict) -> dict:
    """Сверка YAML `longlist` ↔ тело Stage 0: все ли регионы дойдут до PDF.

    Ловит классы дрейфа, из-за которых экспорт молча выдаёт кривой PDF:
      • YAML `longlist:` не распарсился (inline-комментарий на block-ключе и
        т.п.) → пустой список, хотя регионы в теле есть;
      • `longlist_count` ≠ числу YAML-регионов (счётчик/список разъехались);
      • регион есть в теле (`### …`), но нет в YAML (или наоборот) → не попадёт
        в PDF / нарушен порядок;
      • «Что увидишь» уехал в чужую карточку (сдвиг — маркер вне региона).

    Возвращает `{"errors": [...], "warnings": [...]}`. errors → `build_pdf`
    падает с понятным сообщением (лучше, чем кривой PDF); warnings — выводятся.
    """
    fm = parsed.get("frontmatter") or {}
    sections = parsed.get("sections") or []
    errors: list[str] = []
    warnings: list[str] = []

    yaml_names = [(it.get("region") or "").strip()
                  for it in (fm.get("longlist") or []) if it.get("region")]
    ll_count = fm.get("longlist_count")

    # Регион-### под H2 «Longlist…» в порядке тела + преамбула H2 (текст до
    # первого ###) — для детекции сдвига «Что увидишь».
    body_names: list[str] = []
    longlist_preamble = ""
    whatsee_total = 0
    for sec in sections:
        if not (sec.get("heading") or "").startswith(_LONGLIST_H2_PREFIX):
            continue
        longlist_preamble = sec.get("body") or ""
        whatsee_total += len(re.findall(r"что\s+увид", longlist_preamble, re.IGNORECASE))
        for ss in _all_subsections(sec):
            nm = (ss.get("heading") or "").strip()
            if nm:
                body_names.append(nm)
                whatsee_total += len(re.findall(r"что\s+увид", ss.get("body") or "",
                                                re.IGNORECASE))

    # E1/E2 — YAML пуст, но регионы ожидаются (тело / счётчик). Главный кейс
    # «молчаливо пустого экспорта».
    if not yaml_names and (body_names or (isinstance(ll_count, int) and ll_count > 0)):
        n = len(body_names) or ll_count
        errors.append(
            f"YAML longlist пуст, но регионов ожидается ~{n} (в теле ### "
            f"{len(body_names)}, longlist_count={ll_count}). Вероятно block-ключ "
            f"не распарсился (inline-комментарий на `longlist:`?) или YAML-дрейф.")

    # E3 — счётчик ≠ фактическому числу YAML-регионов.
    if isinstance(ll_count, int) and yaml_names and ll_count != len(yaml_names):
        errors.append(f"longlist_count={ll_count} ≠ числу YAML-регионов "
                      f"{len(yaml_names)} — счётчик и список разъехались.")

    # W1 — YAML-регион без тела → карточка без описания.
    for nm in yaml_names:
        if (_find_subsection(sections, _LONGLIST_H2_PREFIX, nm) is None
                and _find_subsection(sections, _UNIVERSE_H2_PREFIX, nm) is None):
            warnings.append(f"регион «{nm}» — нет тела (### {nm}); карточка без описания.")

    # W2 — регион в теле Longlist, но не в YAML → не попадёт в PDF.
    for nm in body_names:
        if not any(_region_matches(nm, y) for y in yaml_names):
            warnings.append(f"в теле есть «### {nm}», но его нет в YAML longlist "
                            f"— регион не попадёт в PDF.")

    # W3 — порядок YAML ≠ порядку тела (по общим именам).
    matched = [next((y for y in yaml_names if _region_matches(nm, y)), None)
               for nm in body_names]
    body_order = [y for y in matched if y]
    yaml_order = [y for y in yaml_names if y in body_order]
    if body_order and body_order != yaml_order:
        warnings.append("порядок регионов в теле ≠ порядку в YAML longlist "
                        f"(тело: {body_order}; YAML: {yaml_order}).")

    # W4 — сдвиг «Что увидишь»: маркер в преамбуле Longlist (вне региона) или
    # число маркеров ≠ числу регионов.
    if re.search(r"что\s+увид", longlist_preamble, re.IGNORECASE):
        warnings.append("«Что увидишь» найден в преамбуле Longlist (вне ### региона) "
                        "— вероятно стоит ПЕРЕД заголовком и уедет в чужую карточку (сдвиг).")
    if yaml_names and whatsee_total and whatsee_total != len(yaml_names):
        warnings.append(f"«Что увидишь» встречается {whatsee_total}× при "
                        f"{len(yaml_names)} регионах — возможен сдвиг/пропуск описаний.")

    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Helpers для cover/обложки
# ---------------------------------------------------------------------------


def _humanize_regions(trip_id: str, *, join: str = " и ") -> str:
    """`камбоджа_лаос_2026-02` → «Камбоджа и Лаос»; `вьетнам_север_…` →
    «Северный Вьетнам» (квалификатор стороны света → прилагательное)."""
    return cover_common.humanize_trip_geo(trip_id, join=join, default="")


def _season_from_trip_id(trip_id: str) -> str | None:
    """`…_2026-02` → «февраль 2026»."""
    m = re.search(r"_(\d{4})-(\d{2})$", trip_id or "")
    if not m:
        return None
    name = _MONTHS_RU.get(m.group(2))
    return f"{name} {m.group(1)}" if name else None


def _tempo_display(value: str | None) -> str | None:
    """`slow` → «размеренный»; passthrough иначе."""
    if not value:
        return None
    mapping = {
        "slow":     "размеренный",
        "balanced": "сбалансированный",
        "active":   "активный",
    }
    return mapping.get(value.strip().lower(), value)


def _trip_format_display(value: str | None) -> str | None:
    """`explicit_list` → «явный список»; неизвестное — passthrough.

    Ярлык — из taxonomy (`scope_format`): раньше здесь был свой словарь, и он
    печатал EN («explicit list») в подзаголовок обложки.
    """
    if not value:
        return None
    return taxonomy.label("scope_format", value.strip().lower())


def _cover_title(extracted: dict) -> str:
    """Презентационный заголовок обложки.

    Если polish дал чистый H1 (без pipeline-жаргона) — используем его.
    Иначе синтезируем «{регионы} · регионы для DR».
    """
    raw = (extracted.get("title") or "").strip()
    if raw and not re.search(r"stage|региональное\s+сужение", raw, re.IGNORECASE):
        return raw
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    regions = tp.get("регионы") or _humanize_regions(fm.get("trip_id") or "")
    return f"{regions} · регионы для маршрутного списка" if regions else "Регионы для маршрутного списка"


def _cover_subtitle(extracted: dict) -> str:
    """Подзаголовок: сезон + длительность + формат."""
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    season = tp.get("сезон") or _season_from_trip_id(fm.get("trip_id") or "")
    parts: list[str] = []
    if season:
        parts.append(season)
    nights = fm.get("duration_nights")
    if nights:
        parts.append(f"{nights} ночей")
    fmt = _trip_format_display(fm.get("trip_format"))
    if fmt:
        parts.append(fmt)
    return " · ".join(parts)


def _cover_key_params(extracted: dict) -> list[tuple[str, str]]:
    """Строки таблицы ключевых параметров под hero-блоком."""
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    quotas = fm.get("country_quota") or []
    countries = (", ".join(q.get("country") or "" for q in quotas if q.get("country"))
                 if quotas else None)
    rows = cover_common.passport_rows(
        who=tp.get("группа"),
        geo=countries, geo_label="Страны",
        season=tp.get("сезон") or _season_from_trip_id(fm.get("trip_id") or ""),
        duration=(f"{fm['duration_nights']} ночей" if fm.get("duration_nights") else None),
        tempo=tp.get("темп") or _tempo_display(fm.get("tempo")),
    )
    if fm.get("longlist") and len(fm["longlist"]) > 0:
        ll = len(fm["longlist"])
        rows.append(("Регионов в выборке (→ DR)", str(ll)))
    exc = fm.get("excluded_regions") or []
    if exc:
        rows.append(("Кандидатов на замену", str(len(exc))))
    if fm.get("total_regions_analyzed"):
        rows.append(("Проанализировано регионов", str(fm["total_regions_analyzed"])))
    if fm.get("formula_target_nights_per_region"):
        rows.append((
            "Цель по ночам/регион",
            f"~{fm['formula_target_nights_per_region']:.1f}",
        ))
    return rows


# ---------------------------------------------------------------------------
# Card mapping
# ---------------------------------------------------------------------------


# Семантика season-note → цвет side-badge.
#
# Принимаем длинное note (например, «сухо, для парка комфортно. Провинция
# Сиемреап приняла перемещённых из приграничья — [требует проверки: ...]»)
# и извлекаем только короткий tag (ok / risk / bad / blocked) — для chip
# места меньше, длинное пояснение есть в md-источнике и в honest assessment.
_SEASON_TAG_RE = re.compile(
    r"\b(blocked|bad|плохо|закрыт[оа]?|недоступ[а-я]*|risk|риск|мгла|"
    r"советую\s+отложить|пыль|ок|ok|сух[оа]?|комфортно)\b",
    re.IGNORECASE,
)


def _season_chip(note: str | None) -> tuple[str, str] | None:
    """Короткий chip из (возможно длинного) season-note.

    Логика:
      • «blocked / bad / закрыт / недоступ» → красный chip «сезон: blocked».
      • «risk / мгла / пыль» → жёлтый chip «сезон: risk».
      • Только «ok / сухо / комфортно» (нет risk-сигналов) → chip не рисуется
        (нет смысла привлекать внимание к нормальному случаю).
      • Не нашли ни одного известного тэга → жёлтый chip с первыми 20
        символами note (страховка для не-канонических формулировок).
    """
    if not note:
        return None
    low = note.strip().lower()
    tags = [m.group(1).lower() for m in _SEASON_TAG_RE.finditer(low)]
    if not tags:
        # Нет известных tag'ов — берём первое слово как-есть, обрежем.
        short = low.split(",")[0].split(".")[0][:20]
        return (f"сезон: {short}", COLORS["warning"]) if short else None
    # Категоризация по приоритету: red > yellow > green (зелёный не рисуем).
    if any(t in {"blocked", "bad", "плохо"} or t.startswith(("закрыт", "недоступ"))
           for t in tags):
        return ("сезон: blocked", COLORS["danger"])
    if any(t in {"risk", "риск", "мгла", "пыль"} for t in tags):
        return ("сезон: risk", COLORS["warning"])
    return None  # только ok/сухо/комфортно — chip не нужен


def _region_to_card(region: Region) -> "Any":
    """Преобразовать Region → entity_card."""
    color = ROLE_BADGES.get(_role_to_badge_key(region.role), ROLE_BADGES["Supporting"])["color"]

    # — Side badges —
    side: list[tuple[str, str]] = []
    if region.reserve_for:
        # Полная подпись «резерв → {регион}» — пользователь сразу видит пару.
        side.append((f"резерв → {region.reserve_for}", COLORS["warning"]))
    if region.is_non_canonical:
        side.append(("вне путеводителей", COLORS["role_niche"]))
    season_chip = _season_chip(region.season_note)
    if season_chip:
        side.append(season_chip)

    # — Meta line —
    meta_parts: list[str] = []
    if region.density:
        meta_parts.append(f"density: {region.density}")
    if region.nights_min and region.nights_optimum:
        meta_parts.append(f"{region.nights_min}–{region.nights_optimum} ночей")
    elif region.nights_optimum:
        meta_parts.append(f"~{region.nights_optimum} ночей")
    if region.country:
        meta_parts.append(region.country.lower())
    meta_line = " · ".join(meta_parts) if meta_parts else None

    # — Google Images link на заголовок —
    google_q = quote_plus(region.name)
    title_link = f"https://www.google.com/search?tbm=isch&q={google_q}"

    return pdf_lib.entity_card(
        title=region.name,
        accent_color=color,
        badge=_STATUS_SELECTED,            # ✓ идёт в DR (role — в заголовке группы)
        meta_line=meta_line,
        body=region.description or None,
        body_bullets=region.description_bullets or None,
        side_badges=side or None,
        title_link=title_link,
    )


# Пометка статуса региона в единой «вселенной»: ✓ в DR / ◌ кандидат на замену.
_STATUS_SELECTED = ("✓ идёт в DR", "#16a34a")        # зелёный
_STATUS_CANDIDATE = ("◌ кандидат на замену", "#64748b")  # slate


def _excluded_to_card(ex: "ExcludedRegion") -> "Any":
    """Кандидат-на-замену (excluded) → entity_card с пометкой ◌ + условием swap'а."""
    color = (ROLE_BADGES.get(_role_to_badge_key(ex.role), {"color": _STATUS_CANDIDATE[1]})["color"]
             if ex.role else _STATUS_CANDIDATE[1])
    google_q = quote_plus(ex.name)
    title_link = f"https://www.google.com/search?tbm=isch&q={google_q}"
    meta_line = f"не вошло: {ex.reason}" if ex.reason else None
    return pdf_lib.entity_card(
        title=ex.name,
        accent_color=color,
        badge=_STATUS_CANDIDATE,
        meta_line=meta_line,
        body=ex.description or None,
        body_bullets=ex.description_bullets or None,
        title_link=title_link,
    )


def _universe_groups(longlist: list, excluded: list) -> list:
    """Слить выбранные (longlist, ✓) и кандидатов (excluded, ◌) в единые
    role-группы для «вселенной».

    Возвращает `[(display, color, anchor_key, [(obj, selected), …]), …]` в
    порядке Core → Supporting → Niche → Borderline. Кандидаты без распознанной
    role (universe не по role) → хвостовая группа «Кандидаты на замену».
    """
    sel_by_role: dict = {role: regs for role, regs in _group_by_role(longlist)}
    cand_by_role: dict = {}
    cand_norole: list = []
    for e in excluded:
        if e.role in _ROLE_ORDER:
            cand_by_role.setdefault(e.role, []).append(e)
        else:
            cand_norole.append(e)

    groups: list = []
    for role in _ROLE_ORDER:
        items = ([(r, True) for r in sel_by_role.get(role, [])]
                 + [(e, False) for e in cand_by_role.get(role, [])])
        if items:
            color = ROLE_BADGES.get(_role_to_badge_key(role),
                                    ROLE_BADGES["Supporting"])["color"]
            groups.append((_ROLE_DISPLAY.get(role, role.title()), color,
                           f"group-{role}", items))
    if cand_norole:
        groups.append(("Кандидаты на замену", _STATUS_CANDIDATE[1],
                       "group-candidates", [(e, False) for e in cand_norole]))
    return groups


def _universe_card(obj, selected: bool) -> "Any":
    """(Region|ExcludedRegion, selected) → entity_card."""
    return _region_to_card(obj) if selected else _excluded_to_card(obj)


def _role_to_badge_key(role: str) -> str:
    """`core` → `Core` (ключи ROLE_BADGES капитализированы)."""
    return role[:1].upper() + role[1:].lower() if role else "Supporting"


_ROLE_ORDER = ["core", "supporting", "niche", "borderline"]
# Видимые (русские) названия role-групп. Машинные ключи role в YAML/спеке
# остаются английскими (core/supporting/niche/borderline) — это контракт;
# русифицируется только отображение. Расшифровка категорий — в легенде-врезке.
_ROLE_DISPLAY = {
    "core":        "Ядро поездки",
    "supporting":  "Дополнительные",
    "niche":       "Нишевые",
    "borderline":  "Пограничные",
}


def _group_by_role(regions: list[Region]) -> list[tuple[str, list[Region]]]:
    """Сгруппировать regions по role в фиксированном порядке."""
    groups: dict[str, list[Region]] = {r: [] for r in _ROLE_ORDER}
    for r in regions:
        groups.setdefault(r.role, []).append(r)
    # Reserve-карточки желательно поместить РЯДОМ с их парой —
    # ставим reserve сразу после соответствующего core/supporting региона.
    out: list[tuple[str, list[Region]]] = []
    for key in _ROLE_ORDER:
        items = groups.get(key) or []
        if not items:
            continue
        ordered = _order_with_reserves(items)
        out.append((key, ordered))
    return out


def _order_with_reserves(regions: list[Region]) -> list[Region]:
    """Reserve-регион ставим сразу после своего substituted-региона (если он
    в той же group; иначе оставляем в конце group'ы).
    """
    by_name = {r.name: r for r in regions}
    inserted: set[str] = set()
    out: list[Region] = []
    for r in regions:
        if r.reserve_for:
            continue  # пока пропускаем; вставим после подзамещаемого
        if r.name in inserted:
            continue
        out.append(r)
        inserted.add(r.name)
        # Найти reserve-карточку для этого региона.
        for cand in regions:
            if cand.reserve_for and cand.reserve_for.strip().lower() == r.name.strip().lower():
                if cand.name not in inserted:
                    out.append(cand)
                    inserted.add(cand.name)
    # Reserves, чей parent не в группе — кладём в конец.
    for r in regions:
        if r.name not in inserted:
            out.append(r)
            inserted.add(r.name)
    return out


# ---------------------------------------------------------------------------
# Build PDF
# ---------------------------------------------------------------------------


def build_pdf(extracted: dict, output_path: str | Path, *, recipient: str = "self") -> str:
    """Собрать PDF Stage 0 из извлечённой структуры."""
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 0 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    # Гейт целостности longlist: лучше упасть с понятным сообщением, чем
    # выдать кривой PDF с пропавшими/сдвинутыми регионами (см. validate_longlist).
    errs = extracted.get("validation_errors") or []
    if errs:
        raise RuntimeError(
            "Stage 0 export — несоответствие longlist (PDF не собран):\n  - "
            + "\n  - ".join(errs)
            + "\nИсправь 0_scope.md / polished.md и повтори.")
    for w in extracted.get("warnings") or []:
        print(f"[stage0 warning] {w}", file=sys.stderr)
    styles = pdf_lib.get_styles()
    # Stage 0 — презентационная витрина (landscape); prose-секции
    # («Честная оценка», «Контекст поездки») должны читаться без
    # напряжения. Поднимаем body/bullet ~12.5pt локально — глобальный
    # LAYOUT["size_body"] (Stage 4/5) не трогаем.
    styles["body"] = _bump_font(styles["body"], size=12.5, leading=18)
    styles["bullet"] = _bump_font(styles["bullet"], size=12.5, leading=18)
    doc = pdf_lib.make_doc(
        output_path,
        orientation="landscape",
        title=f"Регионы — {extracted['frontmatter'].get('trip_id', '')}",
    )
    pdf_lib.set_footer_text(
        f"создан {extracted['frontmatter'].get('created', '')}".strip(),
    )
    try:
        story: list[Any] = []

        # 1. Hero cover.
        story.append(pdf_lib.hero_cover_block(
            _cover_title(extracted),
            subtitle=_cover_subtitle(extracted),
        ))
        story.append(pdf_lib.spacer(14))

        # 1.5 Ключевые параметры под hero.
        kp_rows = _cover_key_params(extracted)
        if kp_rows:
            story.append(pdf_lib.key_params_table(kp_rows))

        # 2. Контекст + tempo/math. YAML-жаргон (home_eq_start: true,
        #    `trip_id`-ссылки, «Флаг …») вычищаем — это шум для
        #    presentation-PDF (см. _strip_yaml_jargon).
        if extracted["context"]:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Контекст поездки", anchor_slug="context", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            _render_md_paragraphs(story, _prose(extracted["context"]), styles)
        if extracted["tempo"]:
            story.append(pdf_lib.spacer(8))
            story.append(pdf_lib.para("Темп и распределение", styles["h4"],
                                      highlight_todo=False))
            _render_md_paragraphs(story, _prose(extracted["tempo"]), styles)

        # 3. Единая «вселенная» регионов — выбранные (✓ идут в DR) и кандидаты
        #    на замену (◌) в одной сетке, сгруппированы по role. Пользователь
        #    видит ВСЕ регионы и может подставить кандидата вместо выбранного.
        #    В outline выводятся только role-группы (плоское оглавление).
        if extracted["longlist"] or extracted["excluded"]:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar("Все рассмотренные регионы"))
            story.append(pdf_lib.spacer(6))
            story.append(pdf_lib.info_box(
                "**✓ идёт в DR** — регион в выборке для Stage 1. "
                "**◌ кандидат на замену** — рассмотрен, но не вошёл; можно "
                "вернуть в DR вместо любого выбранного (причина — в строке «не "
                "вошло»). Клик по названию — Google-поиск картинок. "
                "Резервные карточки подменяют свою пару, если основной регион "
                "отпадёт после сбора фактов.",
                styles,
            ))
            story.append(pdf_lib.spacer(4))
            story.append(pdf_lib.info_box(
                "**Категории регионов:** "
                "**Ядро** — основа маршрута, почти наверняка в финале; "
                "**Дополнительные** — добор/контраст к ядру; "
                "**Нишевые** — тематические, вне массового туризма; "
                "**Пограничные** — рассмотрены, но скорее под замену; "
                "**вне путеводителей** — направления за пределами стандартных гайдов.",
                styles,
            ))
            story.append(pdf_lib.spacer(8))
            # Дисциплина плотности: ≤4 карточки на страницу; каждая role-группа
            # с новой страницы; >4 карточек → pageful-куски по 4.
            for gi, (display_name, role_color, anchor, items) in enumerate(
                    _universe_groups(extracted["longlist"], extracted["excluded"])):
                if gi > 0:
                    story.append(pdf_lib.page_break())
                n_sel = sum(1 for _, sel in items if sel)
                label = (f"{display_name} · {len(items)}"
                         + (f" ({n_sel} в DR)" if 0 < n_sel < len(items) else ""))
                story.append(pdf_lib.section_bar(
                    label, bg_color=role_color,
                    anchor_slug=anchor, outline_level=0,
                ))
                story.append(pdf_lib.spacer(6))
                for ci, chunk in enumerate(_chunk(items, 4)):
                    if ci > 0:
                        story.append(pdf_lib.page_break())
                        story.append(pdf_lib.section_bar(
                            f"{display_name} · продолжение", bg_color=role_color))
                        story.append(pdf_lib.spacer(6))
                    cards = [_universe_card(obj, sel) for obj, sel in chunk]
                    story.append(pdf_lib.card_grid(cards, cols=2))
                    story.append(pdf_lib.spacer(6))

        # 5. Non-canonical (находки вне путеводителей).
        if extracted["non_canonical"]:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Находки вне путеводителей", anchor_slug="non-canonical",
                outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            _render_non_canonical(story, extracted["non_canonical"], styles)

        # 6. Honest assessment.
        if extracted["honest"]:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Честная оценка", anchor_slug="honest", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            _render_md_paragraphs(story, _prose(extracted["honest"]), styles)

        # 7. Предупреждения (внизу, если есть).
        if extracted["warnings"]:
            story.append(pdf_lib.spacer(10))
            story.append(pdf_lib.para("Предупреждения", styles["h4"], highlight_todo=False))
            story.extend(pdf_lib.bullet_list(extracted["warnings"], styles))

        pdf_lib.build_doc(doc, story, with_background=True)
        return str(output_path)
    finally:
        pdf_lib.set_footer_text("")


def _chunk(items: list, size: int) -> list[list]:
    """Разбить items на куски размером не более `size`. Аналог itertools.batched."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def _bump_font(style: "Any", *, size: float, leading: float) -> "Any":
    """Сделать копию ParagraphStyle с новым размером шрифта и интерлиньяжем.

    Используется в Stage 0 чтобы локально поднять body/bullet шрифт
    (landscape-витрина требует чуть крупнее, чем portrait Stage 5).
    """
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        style.name + "_stage0", parent=style,
        fontSize=size, leading=leading,
    )


def _render_md_paragraphs(story, body: str, styles) -> None:
    """Простой markdown-renderer: bullets / параграфы. Для Stage 0 этого
    достаточно (контекст / honest / tempo — короткие prose-блоки).
    """
    if not body or not body.strip():
        return
    # Разбиваем на блоки по пустой строке.
    current: list[str] = []
    blocks: list[list[str]] = []
    for ln in body.splitlines():
        if ln.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        blocks.append(current)

    for block in blocks:
        if all(ln.lstrip().startswith("- ") for ln in block if ln.strip()):
            items = [ln.lstrip()[2:].strip() for ln in block if ln.strip()]
            story.extend(pdf_lib.bullet_list(items, styles))
        else:
            story.append(pdf_lib.para(
                " ".join(ln.strip() for ln in block), styles["body"],
            ))


def _render_non_canonical(story, items: list[NonCanonical], styles) -> None:
    """Non-canonical findings: info_box на каждый элемент со статусом."""
    for item in items:
        status_text = "в выборке" if item.status == "in_longlist" else "вне выборки"
        text = f"**{item.name}** ({status_text}). {item.interest_match}"
        if item.reason:
            text += f" — {item.reason}"
        story.append(pdf_lib.info_box(text, styles))
        story.append(pdf_lib.spacer(4))


# ---------------------------------------------------------------------------
# Renderer entry point + регистрация
# ---------------------------------------------------------------------------


def render_stage0(
    parsed: dict,
    *,
    recipient: str = "self",
    output_path: str | Path,
    **_kw: Any,
) -> "_renderer.RenderRequest":
    """Главный entry-point: распарсенный 0_scope → PDF + RenderRequest."""
    extracted = extract_content(
        parsed, input_path=[_kw.get("source_file"), output_path])
    pdf_path = build_pdf(extracted, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage":          "0_scope",
            "trip_id":        parsed.get("trip_id"),
            "recipient":      recipient,
            "longlist_count": len(extracted["longlist"]),
            "excluded_count": len(extracted["excluded"]),
        },
        metadata={
            "trip_id":     parsed.get("trip_id"),
            "stage":       parsed.get("stage"),
            "recipient":   recipient,
            "font_family": pdf_lib._ACTIVE_FAMILY,
        },
        notes=[],
    )


# Регистрация — выполняется при импорте модуля.
_renderer.register_renderer("0_scope", "pdf", render_stage0)

"""stages/stage1.py — экстрактор контента + PDF builder для Stage 1.

**Контракт формата** артефакта (20 полей карточки, маркеры, секции) — канон
`references/stage1/stage1-output-spec.md`; сверка — `tests/test_format_contract.py`.

Stage 1 — DR-база отчётов независимых путешественников (20-полевые
карточки авторов сгруппированы по регионам). PDF (self) — portrait A4,
**structured reference-архив**: cover → сводка META-DIAGNOSTICS →
региональные секции с карточками → tails (источники, caveats).

Структура PDF (portrait A4):
  1. Cover (cover_title + cover_subtitle + key_params_table).
     Без hero-блока — Stage 1 reference-документ, не presentation.
  2. Сводка META-DIAGNOSTICS: таблица «Покрытие по регионам» (ссылки
     на каждую секцию региона), bullet-lists распределений (стили /
     сезоны / фокус / языки), WARN-флаги как warning_box.
  3. Карточки по регионам: section_bar per region с цветом из
     REGION_PALETTE; sequential cards (НЕ grid — карточки разной
     длины, grid даёт пустоты). Critical-карточки сопровождаются
     warning_box с цитатой жалоб (поле 18).
  4. Tails: источники вне seed-списка, источники tried-but-failed,
     сезонные caveat'ы.

Outline: каждая карточка — пункт верхнего уровня формата
«N · Автор — «Название отчёта»». Регионы в outline НЕ выводятся —
это визуальные разделители, не якоря. Сводка / Tails — отдельные
top-level пункты.

Stage 1 input может быть:
  • Pure DR output (Mode A.wrap до polish) — без YAML frontmatter, H1
    «Stage 1: Сырая структурированная база…», карточки и
    META-DIAGNOSTICS в виде markdown'а.
  • Polished `1_dr_reports.md` с YAML шапкой (после polish или после
    Mode A.wrap+save).
  • Mode B-расширенный файл с awd.ru карточками — добавлены через
    `merge_dr_additions.py`, YAML получил `sample_curation_note` с
    номерами добавленных карточек. Карточки в теле продолжают
    нумерацию.

Парсер устойчив ко всем трём вариантам — YAML опционален, region
fallback на имена H2, sample_curation_note рендерится info-box'ом
если присутствует.
"""
from __future__ import annotations

import datetime as _dt
import re
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
    from export.style import COLORS, REGION_PALETTE   # type: ignore[no-redef]
else:
    from .. import adapter as _adapter
    from .. import pdf_lib
    from .. import renderer as _renderer
    from .. import cover_common
    from .. import travelers as _travelers
    from ..style import COLORS, REGION_PALETTE

try:  # SSOT ярлыков (report_style) — scripts/taxonomy.py
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import taxonomy


# ---------------------------------------------------------------------------
# Polish-маркеры
# ---------------------------------------------------------------------------

# `[[поездка: …]]` — общий со Stage 0/4: ключевые параметры обложки.
_TRIP_MARKER_RE = re.compile(r"\[\[\s*поездка:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)

# `[[карточка: tonality: critical | focus: photo | flags: residence]]` —
# Stage 1 специфичный маркер. Polish T3 вставляет перед каждой `### Карточка N`.
# Опциональный — fallback парсер читает inline-суффикс H3 и grep по полю 18.
_CARD_MARKER_RE = re.compile(r"\[\[\s*карточка:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)


def _parse_marker_kv(s: str) -> dict:
    """Распарсить `k: v | k: v` (как в `[[поездка: …]]`)."""
    out: dict = {}
    for part in s.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _parse_trip_marker(body: str) -> dict:
    """`[[поездка: …]]` → dict ключевых параметров поездки."""
    if not body:
        return {}
    m = _TRIP_MARKER_RE.search(body)
    return _parse_marker_kv(m.group(1)) if m else {}


# ---------------------------------------------------------------------------
# Карточки: парсинг 20 полей
# ---------------------------------------------------------------------------

# Карточный H3: `### Карточка 1` или `### Карточка 4 — tonality: critical` или
# `### Карточка 23 — ФЕВРАЛЬ 2026, фестиваль` (произвольный суффикс после «—»).
_CARD_H3_RE = re.compile(
    r"^###\s+Карточка\s+(\d+)\s*(?:[—–-]\s*(.+?))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Поле карточки: «N. **Label:** value» — primary форма.
# Label = `[^*]+?` (lazy, без `*`, но допускает `:` внутри — критично для
# заголовков типа «**Жалобы / tonality: critical:**»).
_FIELD_BOLD_RE = re.compile(
    r"^\s*(\d+)\.\s+\*\*([^*]+?):\*\*\s*(.*)$",
)
# Fallback: «N. Label: value» (без bold).
_FIELD_PLAIN_RE = re.compile(
    r"^\s*(\d+)\.\s+([^:*]{2,40}?):\s*(.+)$",
)
# Fallback fallback: просто «N. value» — без явного label.
_FIELD_BARE_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")

# Канонические имена 20 полей (для нормализации lookup).
_FIELD_NAMES = {
    1:  "URL и название",
    2:  "Платформа / язык",
    3:  "Автор",
    4:  "Дата публикации",
    5:  "Месяц/год поездки, длительность",
    6:  "Сезон",
    7:  "Состав группы",
    8:  "Возрастной диапазон",
    9:  "Стиль",
    10: "Темп",
    11: "Транспорт",
    12: "Размещение",
    13: "Главный фокус",
    14: "POI с тональностью",
    15: "Скрытые жемчужины",
    16: "Логистические заметки",
    17: "Диетические ограничения",
    18: "Жалобы",
    19: "Главная рекомендация",
    20: "Признаки фото-интересов",
}

# Значения, которые трактуются как «поле пустое» — не рендерим.
_EMPTY_VALUES_RE = re.compile(
    r"^\s*(?:—|–|-|не\s+указан[оа]?|не\s+уточнен[оа]?|не\s+упомянут[оа]?|n/a|none|—\s*$)\s*$",
    re.IGNORECASE,
)


def _is_empty_value(v: str | None) -> bool:
    if not v or not v.strip():
        return True
    return bool(_EMPTY_VALUES_RE.match(v.strip()))


def _parse_card_fields(body: str) -> dict[int, dict[str, str]]:
    """Распарсить тело карточки в dict[field_num] = {label, value, raw}.

    Возвращает для каждого распознанного поля dict:
      • `label` — текст до `:` (для bold — без `**`-обёртки); для bare
        формы — пустая строка.
      • `value` — текст после `:`.
      • `raw` — полная строка label + «: » + value; нужно для критичных
        полей вроде 18, где маркер «tonality: critical» обычно живёт в
        label, а не в value, и нужен grep по всей строке.

    Resilient к вариациям:
      • `N. **Label:** value` (canonical с polish или DR-output);
      • `N. Label: value` (без bold);
      • `N. value` (без label вовсе — `label` будет пустым);
      • multi-line value: строки без `N.`-префикса и без `### `/`## ` /
        полишных маркеров идут как continuation предыдущего поля.
    """
    fields: dict[int, dict[str, str]] = {}
    used: set[int] = set()
    current_num: int | None = None
    current_label: str = ""
    current_lines: list[str] = []

    def _assign(literal: int) -> int:
        """Ключ поля. Толерантно к D3-дрейфу (DR пишет все поля как `1.`):
        при коллизии литерального номера отдаём следующий свободный позиционный
        слот — `1. 1. 1. …` (20 полей в каноническом порядке) → ключи 1..20,
        позиционная идентичность восстановлена. Корректная нумерация (`1,2,3`)
        и разрежённая (`7,9`) сохраняются без изменений.
        """
        if literal not in used:
            used.add(literal)
            return literal
        k = (max(used) + 1) if used else 1
        while k in used:
            k += 1
        used.add(k)
        return k

    def _flush():
        if current_num is not None:
            value = " ".join(s.strip() for s in current_lines if s.strip()).strip()
            if value or current_label:
                raw = f"{current_label}: {value}" if current_label else value
                fields[current_num] = {
                    "label": current_label,
                    "value": value,
                    "raw":   raw,
                }

    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            _flush()
            return fields
        if line.lstrip().startswith("[[") and "]]" in line:
            continue
        if re.match(r"^\s*---\s*$", line):
            _flush()
            return fields
        if line.lstrip().startswith(">"):
            _flush()
            current_num = None
            current_label = ""
            current_lines = []
            continue

        # URL-only bare: `N. https://x.com` — спасаем от PLAIN-regex'а,
        # который иначе разобьёт по двоеточию схемы (label=«https», value=«//…»).
        m_url = re.match(r"^\s*(\d+)\.\s+(https?://\S+)\s*$", line)
        if m_url:
            _flush()
            try:
                current_num = _assign(int(m_url.group(1)))
            except (ValueError, TypeError):
                current_num = None
                current_label = ""
                current_lines = []
                continue
            current_label = ""
            current_lines = [m_url.group(2)]
            continue

        m = _FIELD_BOLD_RE.match(line)
        if not m:
            m = _FIELD_PLAIN_RE.match(line)
        if m:
            _flush()
            try:
                current_num = _assign(int(m.group(1)))
            except (ValueError, TypeError):
                current_num = None
                current_label = ""
                current_lines = []
                continue
            current_label = (m.group(2) or "").strip()
            current_lines = [m.group(3) or ""]
            continue
        m_bare = _FIELD_BARE_RE.match(line)
        if m_bare and current_num is None:
            try:
                current_num = _assign(int(m_bare.group(1)))
                current_label = ""
                current_lines = [m_bare.group(2)]
                continue
            except (ValueError, TypeError):
                pass
        if current_num is not None and line.strip():
            current_lines.append(line)

    _flush()
    return fields


def _fv(fields: dict[int, dict], num: int) -> str | None:
    """Shortcut: достать `value` поля по номеру. None если поля нет."""
    f = fields.get(num)
    return f.get("value") if f else None


def _fraw(fields: dict[int, dict], num: int) -> str | None:
    """Shortcut: достать `raw` (label + value) поля по номеру."""
    f = fields.get(num)
    return f.get("raw") if f else None


def _strip_md_bold(text: str) -> str:
    """`**word**` → `word`. Для случаев когда значение поля само содержит markdown bold."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


# ---------------------------------------------------------------------------
# Tonality / focus / flags извлечение
# ---------------------------------------------------------------------------

# Inline-маркеры tonality, которые встречаются в H3 («Карточка 4 — tonality: critical»)
# и в самом поле 18 («Жалобы / tonality: critical:» или просто содержит «tonality: critical»).
_TONALITY_CRITICAL_RE = re.compile(r"tonality:\s*critical", re.IGNORECASE)

# Слова-индикаторы фото-фокуса в поле 20 («ЯВНЫЕ», «явные» — большими/любым регистром).
_PHOTO_EXPLICIT_RE = re.compile(r"\bявн(?:ые|ое|ая)\b", re.IGNORECASE)

# Канонические focus-теги (короткие).
_FOCUS_TAGS = {
    "фотограф":   "фото",
    "фото":       "фото",
    "photo":      "фото",
    "архитектур": "архитектура",
    "культур":    "культура",
    "природ":     "природа",
    "гастрономи": "гастрономия",
    "food":       "гастрономия",
    "приключени": "приключения",
    "adventure":  "приключения",
    "mix":        "mix",
    "отдых":      "отдых",
}


def _ru_style(text: str) -> str:
    """EN-термины стиля путешествия → русские ярлыки (taxonomy `report_style`).

    Значение поля «Стиль путешествия» и строки META.distributions DR пишет
    свободным текстом («backpacker / mid-range independent с гидом»), поэтому
    подмена — по терминам, а не резолв enum'а: незнакомое остаётся как есть.
    Polish T8 делает то же на уровне markdown'а; функция — страховка на случай
    прогона без polish.
    """
    return taxonomy.localize_terms("report_style", text)


# Поле карточки → группа taxonomy, чьи термины DR пишет внутри его прозы.
# Поле 7 здесь потому, что DR пишет в «Состав группы» тот же словарь стилей
# («organized tour с русскоязычным гидом») — без него на одной карточке
# «Стиль» был бы русским, а «Состав группы» английским.
# Поля 12 («Размещение») в списке НЕТ сознательно: там имена собственные
# отелей («Family Inn», «Luxury Suites»), которые словарь стилей изуродовал бы.
_FIELD_TERM_GROUP = {
    7:  "report_style",   # «Состав группы»
    9:  "report_style",   # «Стиль путешествия»
    13: "report_focus",   # «Главный фокус»: «mix (культура + природа)»
}


def _ru_field_value(num: int, value: str) -> str:
    """Русификация значения поля карточки по его номеру (см. `_FIELD_TERM_GROUP`)."""
    group = _FIELD_TERM_GROUP.get(num)
    return taxonomy.localize_terms(group, value) if group else value


# WARN-N / B1-awd.ru / NOTE префиксы из YAML.meta_diagnostics_warnings —
# срезаем при выводе, чтобы текст начинался с самой формулировки.
_WARN_PREFIX_RE = re.compile(
    r"^\s*\**\s*(?:WARN-?\s*\d+|B\d+[-_][^\s:]+|NOTE|ВНИМАНИЕ|WARNING)\s*\**\s*[:.\-—]?\s*",
    re.IGNORECASE,
)


def _clean_warning_text(text: str) -> str:
    """`WARN-1: 0% местноязычных…` → `0% местноязычных…`. Также bold-обёртку срезаем."""
    if not text:
        return text
    cleaned = _WARN_PREFIX_RE.sub("", text.strip()).strip(" *")
    return cleaned or text.strip()


def _warning_dedup_key(text: str) -> str:
    """Ключ дедупа warning'ов: первые 50 символов очищенного текста, lowercase."""
    return _clean_warning_text(text).lower().replace(" ", "")[:50]


_PIPELINE_SCRIPT_RE = re.compile(r"\s*через\s+\S+\.py")


def _strip_pipeline_script_ref(text: str) -> str:
    """«…добавлены вручную через merge_dr_additions.py» → «…добавлены вручную».

    Имя пайплайн-скрипта — внутренняя механика, пользователю не нужна
    (`sample_curation_note` info-box Mode B, Р11)."""
    if not text:
        return text
    return _PIPELINE_SCRIPT_RE.sub("", text)


# Длинные скобочные перечисления (>40 симв) — авиалинии, цены, маршруты —
# срезаем из полей 11 (Транспорт) и 12 (Размещение). 40 — порог по
# калибровке КЛТ_1: «(рейсы AirAsia, Asiana, …)» 280 симв; «(3 ночи)» 8 симв.
_LONG_PARENS_RE = re.compile(r"\s*\([^)]{40,}\)")


def _clean_transport(text: str) -> str:
    """Поле 11: срезать перечисления в скобках, дедуп типов по первому слову.

    Дедуп по первому слову («Тук-тук по храмам; тук-тук в Pub Street; авиа»
    → «Тук-тук по храмам; авиа»). Длинные скобки (>40 симв) — убираются
    (авиалинии, тарифы, бренды).
    """
    if not text:
        return text
    cleaned = _LONG_PARENS_RE.sub("", text)
    parts = re.split(r"\s*;\s*", cleaned)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        p = p.strip(" ,;")
        if not p:
            continue
        # Первое слово как ключ дедупа (lowercase, без пунктуации).
        words = re.findall(r"\w+", p.lower())
        first = words[0] if words else ""
        if first and first in seen:
            continue
        if first:
            seen.add(first)
        out.append(p)
    return "; ".join(out).strip(" ;,") if out else text.strip()


# Тип размещения — keyword → label. Order: длинные/специфичные первыми.
_ACCOMMODATION_TYPES = [
    (re.compile(r"\bhomestay\b|\bхомстей\b|\bхоумстэй\b", re.IGNORECASE), "homestay"),
    (re.compile(r"\bgu?esthouse\b|\bгест[хх][аоу]?у?з?\b", re.IGNORECASE), "гестхаус"),
    (re.compile(r"\bhostel\b|\bхостел\b|\bдорм\w*\b|\bdorm\b", re.IGNORECASE), "хостел"),
    (re.compile(r"\bluxury\b|\bлюкс\b|\bresort\b|\bкурорт\b", re.IGNORECASE), "luxury"),
    (re.compile(r"\bapartment\b|\bквартир\w*\b|\bапартамент\w*\b", re.IGNORECASE), "квартира"),
    (re.compile(r"\bprivate\s+rooms?\b", re.IGNORECASE), "private room"),
    (re.compile(r"\bкемпинг\b|\bcamping\b|\bпалат\w+\b", re.IGNORECASE), "кемпинг"),
    (re.compile(r"\bбунгало\b|\bbungalow\b", re.IGNORECASE), "бунгало"),
    (re.compile(r"\briverside\b|\bна\s+берегу\b", re.IGNORECASE), "riverside"),
    (re.compile(r"\bотел[ьея]?\b|\bhotel\b|\bвилла\b|\bvilla\b", re.IGNORECASE), "отель"),
]


def _extract_accommodation_type(text: str) -> str | None:
    """Из поля 12 извлечь тип(ы) размещения. None если не определилось.

    «Koulen Hotel (3 ночи, бассейн на крыше…)» → «отель».
    «Отель в Сием-Рипе + хостел в Пномпене» → «отель, хостел».
    «не уточнено» → None (bullet не выводится).
    """
    if not text or _is_empty_value(text):
        return None
    found: list[str] = []
    seen: set[str] = set()
    for pat, label in _ACCOMMODATION_TYPES:
        if pat.search(text) and label not in seen:
            found.append(label)
            seen.add(label)
    return ", ".join(found) if found else None


def _normalize_focus(field13: str | None) -> str:
    """Главный фокус (поле 13) → короткий тэг.

    «mix (архитектура + культура)» → «mix» (mix имеет приоритет — он явно
    декларирован автором как «всего понемногу»).
    «фотография + архитектура» → «фото» (фотофокус — сильный сигнал, важнее
    конкретной тематики).
    «архитектура» → «архитектура».
    """
    if not field13 or _is_empty_value(field13):
        return "mix"
    low = field13.strip().lower()
    # 1. Mix объявлен явно — это всегда mix, независимо от перечисленного.
    if re.search(r"\bmix\b", low):
        return "mix"
    # 2. Фото-фокус — сильный сигнал, важнее тематических ключей.
    for key in ("фотограф", "фото", "photo"):
        if key in low:
            return _FOCUS_TAGS[key]
    # 3. Прочие тематические ключи — по порядку приоритета.
    priority = ["архитектур", "культур", "природ", "гастрономи",
                "food", "приключени", "adventure", "отдых"]
    for key in priority:
        if key in low:
            return _FOCUS_TAGS[key]
    return "mix"


def _focus_color(focus: str) -> str:
    """Цвет badge'а по focus-тэгу — берём из REGION_PALETTE циклически.

    Не семантический mapping (нет canonical category color), а просто
    стабильное hash-распределение цветов на множество фокусов.
    """
    keys = ["mix", "архитектура", "культура", "природа", "фото",
            "гастрономия", "приключения", "отдых"]
    if focus in keys:
        return REGION_PALETTE[keys.index(focus) % len(REGION_PALETTE)]
    return COLORS["primary"]


def _detect_tonality(
    h3_suffix: str | None,
    marker: dict | None,
    field18: str | None,
) -> bool:
    """True если карточка critical. Приоритет: marker → H3 suffix → grep field 18."""
    if marker and marker.get("tonality", "").lower() == "critical":
        return True
    if h3_suffix and _TONALITY_CRITICAL_RE.search(h3_suffix):
        return True
    if field18 and _TONALITY_CRITICAL_RE.search(field18):
        return True
    return False


def _detect_flags(marker: dict | None, field20: str | None) -> set[str]:
    """Извлечь side-флаги: photo (по полю 20 = «ЯВНЫЕ» или маркеру), residence."""
    flags: set[str] = set()
    if marker and marker.get("flags"):
        for f in re.split(r"[,;]\s*", marker["flags"]):
            f = f.strip().lower()
            if f:
                flags.add(f)
    if field20 and _PHOTO_EXPLICIT_RE.search(field20):
        flags.add("photo")
    return flags


# ---------------------------------------------------------------------------
# META-DIAGNOSTICS парсер (структурный, из body — устойчив к иерархии H1)
# ---------------------------------------------------------------------------

# Markdown-парсер в parser.py трактует ## под # как siblings (H1 не контейнер),
# поэтому META-секции лучше парсить из raw body по маркеру `^# META-DIAGNOSTICS`.

_META_H1_RE = re.compile(r"^#\s+META-DIAGNOSTICS\s*$", re.MULTILINE | re.IGNORECASE)
_META_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _extract_meta_block(body: str) -> str | None:
    """Вернуть текст после `# META-DIAGNOSTICS` до конца body. None если нет."""
    if not body:
        return None
    m = _META_H1_RE.search(body)
    return body[m.end():] if m else None


def _split_meta_subsections(meta_text: str) -> dict[str, str]:
    """`## Сводка\\n...\\n## Распределение по стилям\\n...` → dict[heading] = body."""
    if not meta_text:
        return {}
    out: dict[str, str] = {}
    matches = list(_META_H2_RE.finditer(meta_text))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(meta_text)
        body = meta_text[start:end].strip("\n")
        out[heading] = body
    return out


def _parse_bullet_list(text: str) -> list[str]:
    """Bullet-блок «- item\\n- item» → list[str] без маркера."""
    if not text:
        return []
    items: list[str] = []
    for ln in text.splitlines():
        m = re.match(r"^\s*[-•*]\s+(.+)$", ln)
        if m:
            items.append(m.group(1).strip())
    return items


def _parse_meta(body: str) -> dict:
    """Распарсить META-DIAGNOSTICS блок body в структуру для PDF.

    Возвращает dict с ключами (все опциональны):
      • coverage_per_region: list[(region, count_text)] — из ## Сводка
        строки «- Сием-Рип и Ангкор: 6 (Карточки …)».
      • distributions: dict[name] = list[str] — распределения по
        стилям/сезонам/фокусу/языкам.
      • poi_critique_per_region: list[(region, count_text)].
      • season_caveat: str — длинная цитата из «## Сезонные caveat'ы …».
      • sources_outside_seed: list[str] — bullet'ы.
      • warnings: list[str] — из «## WARNINGs» (если YAML.meta_diagnostics_warnings нет).
      • sources_tried: list[str] — bullet'ы из «## Источники, что пробовали…».
    """
    meta_text = _extract_meta_block(body)
    if not meta_text:
        return {}
    subs = _split_meta_subsections(meta_text)
    out: dict = {}

    # Сводка → coverage_per_region: «- Регион: N (Карточки X, Y, Z)»
    # Фильтруем мета-строки: «Всего», «Покрытие», «Все регионы», «**...».
    summary = subs.get("Сводка") or ""
    coverage: list[tuple[str, str]] = []
    _META_SUMMARY_KEYS = re.compile(
        r"^\s*\**\s*(всего|покрыти|все\s+регион)",
        re.IGNORECASE,
    )
    for ln in summary.splitlines():
        m = re.match(r"^\s*[-•]\s+(.+?):\s*(.+)$", ln)
        if not m:
            continue
        region = m.group(1).strip().lstrip("*").rstrip("*").strip()
        if _META_SUMMARY_KEYS.match(region):
            continue
        count_text = m.group(2).strip()
        coverage.append((region, count_text))
    if coverage:
        out["coverage_per_region"] = coverage

    # Распределения — несколько ## секций с префиксом «Распределение по …».
    distributions: dict[str, list[str]] = {}
    for heading, sub_body in subs.items():
        if heading.startswith("Распределение по "):
            short = heading[len("Распределение по "):].strip()
            items = _parse_bullet_list(sub_body)
            if items:
                distributions[short] = items
    if distributions:
        out["distributions"] = distributions

    # POI-критика per region.
    for heading, sub_body in subs.items():
        if heading.startswith("POI-критика"):
            crit: list[tuple[str, str]] = []
            for ln in sub_body.splitlines():
                m = re.match(r"^\s*[-•]\s+([^:]+?):\s*(.+)$", ln)
                if m:
                    crit.append((m.group(1).strip(), m.group(2).strip()))
            if crit:
                out["poi_critique_per_region"] = crit

    # Сезонные caveat'ы — длинная цитата.
    for heading, sub_body in subs.items():
        if heading.startswith("Сезонные caveat"):
            text = sub_body.strip()
            if text:
                out["season_caveat"] = text
            break

    # Источники вне seed-списка.
    src_out = subs.get("Источники вне seed-списка (использованные)") \
        or subs.get("Источники вне seed-списка")
    if src_out:
        bullets = _parse_bullet_list(src_out)
        if bullets:
            out["sources_outside_seed"] = bullets

    # WARNINGs — fallback на YAML, но если в YAML пусто — берём отсюда.
    warns = subs.get("WARNINGs") or subs.get("WARNINGS") or subs.get("Warnings")
    if warns:
        out["warnings_from_meta"] = _parse_bullet_list(warns)

    # Источники, что пробовали.
    tried = None
    for heading, sub_body in subs.items():
        if heading.startswith("Источники, кото"):
            tried = sub_body
            break
    if tried:
        bullets = _parse_bullet_list(tried)
        if bullets:
            out["sources_tried"] = bullets

    return out


# ---------------------------------------------------------------------------
# Регионы и карточки: извлечение из sections + body
# ---------------------------------------------------------------------------

# Region H2: `## РЕГИОН 1: Сием-Рип и Ангкор (Siem Reap & Angkor), Камбоджа`.
_REGION_H2_RE = re.compile(
    r"^РЕГИОН\s+\d+\s*[:.]?\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _clean_region_heading(heading: str) -> str:
    """`РЕГИОН 1: Сием-Рип и Ангкор (Siem Reap & Angkor), Камбоджа` → имя без префикса."""
    m = _REGION_H2_RE.match(heading.strip())
    if m:
        return m.group(1).strip()
    return heading.strip()


def _region_slug(name: str, idx: int) -> str:
    """Region name → URL-safe slug для anchor_slug."""
    base = re.sub(r"[^a-zа-яё0-9]+", "-", name.lower()).strip("-")
    return f"region-{idx}-{base}" if base else f"region-{idx}"


def _card_slug(num: int) -> str:
    return f"card-{num}"


@dataclass
class Card:
    """Одна карточка автора (20-полевая)."""
    num: int                                # «### Карточка N»
    h3_suffix: str | None                   # «— tonality: critical» / «— РЕЗИДЕНТ-ОТЧЁТ» / None
    fields: dict[int, dict[str, str]]       # field_num → {label, value, raw}
    marker: dict | None                     # [[карточка: …]] маркер (None если нет)
    region_name: str                        # имя региона (для outline contextual'a)

    # Производные (вычислены при extract).
    is_critical: bool = False
    focus_tag: str = "mix"
    flags: set[str] = field(default_factory=set)
    covered_regions: list[str] = field(default_factory=list)  # из суффикса заголовка


@dataclass
class Region:
    """Региональная секция с карточками."""
    idx: int                                # позиция (для цвета REGION_PALETTE)
    name: str                               # «Сием-Рип и Ангкор (Siem Reap & Angkor), Камбоджа»
    slug: str
    cards: list[Card] = field(default_factory=list)


# Толерантный ЗАГОЛОВОК карточки: `## КАРТОЧКА N`, `**КАРТОЧКА 01**` (bold),
# `### Карточка N`, `Card/Отчёт/Report N`, регистр любой, ведущий ноль ок.
# Захватываем номер и хвост строки (суффикс с покрытыми регионами /
# tonality). `(?![...]–\d)` — не матчить диапазоны «Карточки 1–30».
# (NB: не путать с `_CARD_MARKER_RE` — тот для polish-маркера `[[карточка:]]`.)
_CARD_HEADER_RE = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|\*\*[ \t]*)?"
    r"(?:КАРТОЧКА|Карточка|Card|Отчёт|Отчет|Report)"
    r"[ \t]+0*(\d+)\b(?![ \t]*[–—-][ \t]*\d)"
    r"[ \t]*\*{0,2}[ \t]*(.*?)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
# Не-региональные токены в суффиксе (тональность / фокус / язык / сезон /
# дескрипторы) — такой токен НЕ регион, отбрасываем целиком.
_NON_REGION_RE = re.compile(
    r"критик|tonality|critical|источник|focused|фокус|deep-dive|day\s*trip|"
    r"англояз|резидент|\bпара\b|итинерари|multi-region|обновлен|подборк|"
    r"tripadvisor|tourister|otzyv|отзыв|pikabu|livejournal|\bdrom\b|awd|"
    r"январ|феврал|март|апрел|ма[йя]\b|июн|июл|август|сентябр|октябр|ноябр|декабр|"
    r"\b(?:vi|en|zh|ko|ja|es)\b", re.IGNORECASE)


def _parse_covered_regions(suffix: str | None) -> list[str]:
    """Достать покрытые регионы из суффикса заголовка карточки.

    Регион — свойство POI (Stage 3), но на уровне Stage 1 полезно показать
    «что покрывает отчёт» строкой. Источник — парентеза заголовка
    (`(multi-region: Пекин + Сиань)`, `(Сиань)`, `(Гуйлинь/Яншо)`). Токены с
    тональностью / фокусом / языком / сезоном отбрасываются.
    """
    if not suffix:
        return []
    m = re.search(r"\(([^)]*)\)", suffix)
    inner = m.group(1) if m else suffix
    inner = re.sub(r"^\s*multi-region\s*:\s*", "", inner, flags=re.IGNORECASE)
    out: list[str] = []
    for p in re.split(r"\s*(?:\+|,|/|→|;|\bи\b)\s*", inner):
        p = p.strip(" .—–-[]()").strip()
        # Ведущий топоним: 1–2 капитализированных слова, хвост-дескриптор отсечь
        # (`Шанхай — Юй Юань` → `Шанхай`; `Лоян фестиваль пионов` → `Лоян`).
        lead = re.match(r"([A-ZА-ЯЁ][^\s—–\-\[\]()]*(?:\s+[A-ZА-ЯЁ][^\s—–\-\[\]()]*)?)", p)
        if lead:
            p = lead.group(1).strip()
        # регион: ≥2 симв, с заглавной, есть строчная буква (отсекает `B1`,
        # `КРИТИЧЕСКИЙ`), не год, не дескриптор.
        if (not p or len(p) < 2 or re.fullmatch(r"\d{4}", p)
                or not p[0].isupper() or not re.search(r"[a-zа-яё]", p)
                or _NON_REGION_RE.search(p)):
            continue
        if p not in out:
            out.append(p)
    return out


def _extract_all_cards(parsed: dict) -> list[Card]:
    """Плоский толерантный скан ВСЕХ карточек (без региональной группировки).

    DR-формат карточек варьируется между прогонами (`## КАРТОЧКА N` плоско,
    `**КАРТОЧКА 01**` под `### РЕГИОН N —`, `### Карточка N`), а регион —
    свойство POI (Stage 3), не автора. Поэтому Stage 1 export перестаёт
    группировать по регионам: находит все карточки одним сканом по
    толерантному маркеру и выдаёт их последовательно. Покрытые регионы —
    строкой на карточке (из суффикса заголовка).
    """
    body = parsed.get("body") or ""
    cards: list[Card] = []
    seen: set[int] = set()
    matches = list(_CARD_HEADER_RE.finditer(body))
    for i, m in enumerate(matches):
        try:
            num = int(m.group(1))
        except (ValueError, TypeError):
            continue
        if num in seen:
            continue
        seen.add(num)
        suffix = (m.group(2) or "").strip() or None
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        card_body = body[start:end]
        fields = _parse_card_fields(card_body)
        marker = _find_card_marker_before_h3(body, num)
        h3_suffix = suffix if (suffix and _TONALITY_CRITICAL_RE.search(suffix)) else suffix
        card = Card(
            num=num, h3_suffix=h3_suffix, fields=fields, marker=marker,
            region_name="",
            covered_regions=_parse_covered_regions(suffix),
        )
        card.is_critical = _detect_tonality(h3_suffix, marker, _fraw(fields, 18))
        card.focus_tag = _normalize_focus(_fv(fields, 13))
        card.flags = _detect_flags(marker, _fv(fields, 20))
        cards.append(card)
    cards.sort(key=lambda c: c.num)
    return cards


def _extract_regions_and_cards(parsed: dict) -> list[Region]:
    """[Legacy] Из parsed.sections извлечь регионы и их карточки.

    Сохранена для совместимости; основной путь — `_extract_all_cards`
    (де-регионизация). Регион = H2 «РЕГИОН N:»; карточка = H3 «Карточка N».
    """
    body = parsed.get("body") or ""
    sections = parsed.get("sections") or []

    regions: list[Region] = []
    seen_card_nums: set[int] = set()

    region_idx = 0
    for sec in sections:
        heading = sec.get("heading", "").strip()
        if not _REGION_H2_RE.match(heading):
            continue
        region_idx += 1
        name = _clean_region_heading(heading)
        region = Region(
            idx=region_idx,
            name=name,
            slug=_region_slug(name, region_idx),
        )
        # Карточки — H3 subsections.
        for ss in sec.get("subsections", []):
            card = _build_card_from_subsection(ss, region.name, body)
            if card is not None:
                if card.num in seen_card_nums:
                    continue  # дубль — пропускаем
                seen_card_nums.add(card.num)
                region.cards.append(card)
        regions.append(region)

    # Orphan cards — H3 «Карточка N» вне регионов (sections без РЕГИОН-префикса,
    # либо subsections под non-region H2). Собираем из всего body через regex.
    orphans = _scan_orphan_cards(body, seen_card_nums)
    if orphans:
        extra = Region(
            idx=len(regions) + 1,
            name="Дополнительные карточки",
            slug=f"region-{len(regions) + 1}-extra",
            cards=orphans,
        )
        regions.append(extra)

    return regions


def _build_card_from_subsection(
    ss: dict,
    region_name: str,
    full_body: str,
) -> Card | None:
    """H3-subsection (`### Карточка N — suffix`) → Card.

    `full_body` нужен для поиска [[карточка: …]] маркера, который polish
    T3 ставит ПЕРЕД `### Карточка N` — он не попадает в subsection.body.
    """
    heading = ss.get("heading", "").strip()
    m = re.match(r"^Карточка\s+(\d+)\s*(?:[—–-]\s*(.+))?\s*$", heading, re.IGNORECASE)
    if not m:
        return None
    try:
        num = int(m.group(1))
    except (ValueError, TypeError):
        return None
    h3_suffix = (m.group(2) or "").strip() or None

    fields = _parse_card_fields(ss.get("body") or "")
    marker = _find_card_marker_before_h3(full_body, num)

    card = Card(
        num=num,
        h3_suffix=h3_suffix,
        fields=fields,
        marker=marker,
        region_name=region_name,
    )
    card.is_critical = _detect_tonality(h3_suffix, marker, _fraw(fields, 18))
    card.focus_tag = _normalize_focus(_fv(fields, 13))
    card.flags = _detect_flags(marker, _fv(fields, 20))
    return card


def _find_card_marker_before_h3(body: str, num: int) -> dict | None:
    """Найти `[[карточка: …]]` маркер на 0-3 строки ВЫШЕ `### Карточка N`.

    Polish T3 ставит маркер вплотную перед H3 — обычно прямо предыдущей
    непустой строкой. Допускаем небольшой gap (пустые строки).
    """
    if not body:
        return None
    h3_pat = re.compile(
        rf"^###\s+Карточка\s+{num}(?:\s|$|[—–-])",
        re.MULTILINE | re.IGNORECASE,
    )
    h3_m = h3_pat.search(body)
    if not h3_m:
        return None
    # Окно поиска маркера — 250 символов вверх (≈ 3-5 строк).
    win_start = max(0, h3_m.start() - 250)
    window = body[win_start:h3_m.start()]
    markers = list(_CARD_MARKER_RE.finditer(window))
    if not markers:
        return None
    return _parse_marker_kv(markers[-1].group(1))


def _scan_orphan_cards(body: str, seen_nums: set[int]) -> list[Card]:
    """Найти H3 «### Карточка N» вне региональных секций.

    Применимо когда: pure DR output без региональной H2-группировки,
    либо Mode B добавил карточки под non-РЕГИОН H2.
    """
    if not body:
        return []
    out: list[Card] = []
    for m in _CARD_H3_RE.finditer(body):
        try:
            num = int(m.group(1))
        except (ValueError, TypeError):
            continue
        if num in seen_nums:
            continue
        h3_suffix = (m.group(2) or "").strip() or None
        # Body карточки — от конца H3 до следующего `^### ` или `^## ` или `^# `.
        start = m.end()
        next_h = re.search(r"^#{1,3}\s+", body[start:], re.MULTILINE)
        end = start + next_h.start() if next_h else len(body)
        card_body = body[start:end]
        fields = _parse_card_fields(card_body)
        marker = _find_card_marker_before_h3(body, num)
        card = Card(
            num=num,
            h3_suffix=h3_suffix,
            fields=fields,
            marker=marker,
            region_name="Дополнительно",
        )
        card.is_critical = _detect_tonality(h3_suffix, marker, _fraw(fields, 18))
        card.focus_tag = _normalize_focus(_fv(fields, 13))
        card.flags = _detect_flags(marker, _fv(fields, 20))
        out.append(card)
        seen_nums.add(num)
    out.sort(key=lambda c: c.num)
    return out


# ---------------------------------------------------------------------------
# Извлечение URL и краткого названия из поля 1
# ---------------------------------------------------------------------------

# Поле 1 формата: «https://… — «Название»» или «https://…» или «URL: https://…».
_URL_RE = re.compile(r"https?://[^\s)\]>]+")


def _extract_url_and_title(field1: str | None) -> tuple[str | None, str | None]:
    """Field 1 → (url, short_title).

    Примеры:
      «https://aleksblog.com/angkor/ — «Храмы Ангкора: полное руководство…»»
        → ("https://aleksblog.com/angkor/", "Храмы Ангкора: полное руководство…")
      «https://forum.awd.ru/viewtopic.php?t=123 — «Вьетнам 2024»»
        → (url, "Вьетнам 2024")
      «Boring and Overrated» (без URL — fallback)
        → (None, "Boring and Overrated")
    """
    if not field1:
        return None, None
    field1 = field1.strip()
    url_m = _URL_RE.search(field1)
    url = url_m.group(0).rstrip(".,;)") if url_m else None
    # Title — текст в кавычках («…»/"…"), либо после «—».
    title = None
    title_m = re.search(r"[«\"„]([^»\"”]+)[»\"”]", field1)
    if title_m:
        title = title_m.group(1).strip()
    else:
        # «URL — название» без кавычек.
        if "—" in field1 and url:
            after = field1.split("—", 1)[1].strip()
            if after and not _URL_RE.match(after):
                title = after.strip(" «»\"")
        elif not url:
            # Совсем нет URL — весь field1 = title.
            title = field1.strip(" «»\"")
    return url, title


def _extract_author(field3: str | None) -> str | None:
    """Field 3 → имя автора (без скобок-уточнений типа города).

    «helvhrav (Москва)» → «helvhrav»
    «Алекс (Aleks)» → «Алекс»
    «Дария «Orange Traveler»» → «Дария «Orange Traveler»» (сохраняем)
    """
    if not field3 or _is_empty_value(field3):
        return None
    text = field3.strip()
    # Срезаем `(…)` только если в скобках город / транслитерация (короткое).
    text = _strip_md_bold(text)
    # Не агрессивно режем — пользователь должен узнать автора.
    return text or None


# ---------------------------------------------------------------------------
# Title для outline и cover карточки
# ---------------------------------------------------------------------------


def _card_outline_title(card: Card) -> str:
    """Формат outline-пункта: `N · Автор — «Название»`."""
    author = _extract_author(_fv(card.fields, 3))
    _, title = _extract_url_and_title(_fv(card.fields, 1))
    head = f"{card.num}"
    if author and title:
        head = f"{card.num} · {author} — «{title}»"
    elif author:
        head = f"{card.num} · {author}"
    elif title:
        head = f"{card.num} · «{title}»"
    else:
        head = f"Карточка {card.num}"
    # Обрезаем по длине — outline-панель узкая.
    if len(head) > 90:
        head = head[:87] + "…"
    return head


def _card_visible_title(card: Card) -> str:
    """Header карточки в PDF: `Карточка N · «Название»` (URL — title_link)."""
    _, title = _extract_url_and_title(_fv(card.fields, 1))
    if title:
        return f"Карточка {card.num} · «{title}»"
    return f"Карточка {card.num}"


# ---------------------------------------------------------------------------
# Extract content
# ---------------------------------------------------------------------------


def extract_content(parsed: dict, *, input_path: "Path | None" = None) -> dict:
    """Извлечь структуру для PDF-builder'а из распарсенного 1_dr_reports.md.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10)."""
    fm = parsed.get("frontmatter") or {}
    body = parsed.get("body") or ""

    trip_params = _parse_trip_marker(body)
    resolved_who = _travelers.resolve_travelers(fm, trip_params, input_path)
    if resolved_who:
        trip_params["группа"] = resolved_who
    # Де-регионизация: все карточки одним плоским сканом, без группировки по
    # регионам (регион — свойство POI, Stage 3). Оборачиваем в один нейтральный
    # псевдо-регион «База отчётов», чтобы рендер-цикл по `regions` не менять.
    all_cards = _extract_all_cards(parsed)
    regions = ([Region(idx=1, name="База отчётов", slug="reports", cards=all_cards)]
               if all_cards else [])
    meta = _parse_meta(body)

    # Warnings: канонический источник — YAML.meta_diagnostics_warnings
    # (polish T9 консолидирует туда дедуплицированный список одной фразой
    # на warning). Если YAML пуст — fallback на body ## WARNINGs. Merge
    # двух источников НЕ делаем: при отсутствии polish'а body часто
    # дублирует YAML расширенными формулировками — это даёт визуальные
    # повторы в PDF. Дедуп между YAML и body — задача polish'а, не скрипта.
    warnings: list[str] = []
    seen_keys: set[str] = set()
    yaml_warns = fm.get("meta_diagnostics_warnings") or []
    if isinstance(yaml_warns, list):
        for w in yaml_warns:
            if isinstance(w, str) and w.strip():
                key = _warning_dedup_key(w)
                if key not in seen_keys:
                    seen_keys.add(key)
                    warnings.append(w.strip())
    if not warnings:
        for w in meta.get("warnings_from_meta", []) or []:
            if isinstance(w, str) and w.strip():
                key = _warning_dedup_key(w)
                if key not in seen_keys:
                    seen_keys.add(key)
                    warnings.append(w.strip())

    # Counts derived.
    total_cards = sum(len(r.cards) for r in regions)
    critical_count = sum(1 for r in regions for c in r.cards if c.is_critical)

    return {
        "title":        parsed.get("title"),
        "frontmatter":  fm,
        "trip_params":  trip_params,
        "regions":      regions,
        "cards":        all_cards,
        "meta":         meta,
        "warnings":     warnings,
        "total_cards":  total_cards,
        "critical_count": critical_count,
        # Mode B признак.
        "sample_curation_note": fm.get("sample_curation_note"),
    }


# ---------------------------------------------------------------------------
# Cover helpers
# ---------------------------------------------------------------------------


_MONTHS_RU = {
    "01": "январь", "02": "февраль", "03": "март", "04": "апрель",
    "05": "май", "06": "июнь", "07": "июль", "08": "август",
    "09": "сентябрь", "10": "октябрь", "11": "ноябрь", "12": "декабрь",
}


def _humanize_regions(trip_id: str, *, join: str = " и ") -> str:
    """`камбоджа_лаос_2026-02` → «Камбоджа и Лаос»; `вьетнам_север_…` →
    «Северный Вьетнам» (квалификатор стороны света → прилагательное)."""
    return cover_common.humanize_trip_geo(trip_id, join=join, default="Поездка")


def _yaml_region_names(fm: dict) -> list[str]:
    """Список имён регионов из YAML `regions:` — первичный источник счётчика
    обложки. Де-регионизация Stage 1 схлопывает все карточки в один
    псевдо-регион «База отчётов» — internal `regions`
    (`extracted["regions"]`) для счёта регионов не годится, всегда даёт 1."""
    regions = fm.get("regions")
    if isinstance(regions, list):
        return [str(r).strip() for r in regions if str(r).strip()]
    return []


def _season_from_trip_id(trip_id: str | None) -> str | None:
    if not trip_id:
        return None
    m = re.search(r"_(\d{4})-(\d{2})$", trip_id)
    if not m:
        return None
    name = _MONTHS_RU.get(m.group(2))
    return f"{name} {m.group(1)}" if name else None


def _cover_title(extracted: dict) -> str:
    """`{Регионы} · DR-база отчётов`. Если polish дал чистый H1 — используем."""
    raw = (extracted.get("title") or "").strip()
    if raw and not re.search(r"^stage|сырая\s+структурированная", raw, re.IGNORECASE):
        return raw
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    regions = tp.get("регионы") or _humanize_regions(fm.get("trip_id") or "")
    return f"{regions} · DR-база отчётов" if regions else "DR-база отчётов"


def _cover_subtitle(extracted: dict) -> str:
    """`{сезон} · {N} отчётов · {M} регионов`."""
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    parts: list[str] = []
    season = tp.get("сезон") or fm.get("season") or _season_from_trip_id(fm.get("trip_id"))
    if season:
        parts.append(str(season))
    n_cards = extracted.get("total_cards") or fm.get("reports_count")
    if n_cards:
        parts.append(f"{n_cards} отчётов")
    n_regions = len(_yaml_region_names(fm)) or len(extracted.get("regions") or [])
    if n_regions:
        parts.append(f"{n_regions} регионов")
    return " · ".join(parts)


def _format_dr_run_date(value: Any) -> str | None:
    """YAML `dr_run_date` → отображение. YYYY-MM-DD дословно; «retrospective: today» убираем."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("yyyy-mm-dd", ""):
        return None
    if "today" in s.lower() or "retrospective" in s.lower():
        return None
    return s


def _language_summary(extracted: dict) -> str | None:
    """Из meta.distributions[«языку источника»] → строка «RU 22% · EN 78%»."""
    meta = extracted.get("meta") or {}
    dist = meta.get("distributions") or {}
    lang = dist.get("языку источника") or dist.get("языку")
    if not lang:
        return None
    # bullets вида «RU: 8 отчётов (1, 2, 3, 5, 6, 7, 18, 19) ≈ 22%».
    parts: list[str] = []
    for ln in lang:
        # Процент может быть с десятичной запятой/точкой («≈12,5%») — не
        # обрезать до «5%».
        m = re.match(r"^\s*([A-Za-zА-Яа-я/-]+)[\s:]+.*?(\d{1,3}(?:[.,]\d+)?)\s*%", ln)
        if m:
            parts.append(f"{m.group(1).strip()} {m.group(2)}%")
        elif "WARNING" in ln.upper() or "местн" in ln.lower():
            # «Местные языки: 0% — WARNING» — компактно.
            parts.append("местн. 0%")
    return " · ".join(parts) if parts else None


def _cover_key_params(extracted: dict) -> list[tuple[str, str]]:
    """Строки таблицы ключевых параметров под cover."""
    fm = extracted["frontmatter"]
    tp = extracted.get("trip_params") or {}
    meta = extracted.get("meta") or {}
    # Регионы: YAML `regions:` — первичный источник счётчика.
    # Текст маркера `[[поездка: регионы: …]]` — только fallback, если в YAML
    # регионов нет (сам маркер как текст не парсим по « и » — ломается на
    # составных именах вида «Пекин и окрестности»).
    yaml_regions = _yaml_region_names(fm)
    if yaml_regions:
        # Срезаем латинскую транскрипцию в скобках и финальный «, страна»
        # — иначе строка непомерно длинная.
        geo = " · ".join(r.split("(")[0].strip().rstrip(",") for r in yaml_regions)
        n_regions = len(yaml_regions)
    else:
        regions = extracted.get("regions") or []
        geo = (" · ".join(r.name.split("(")[0].strip().rstrip(",") for r in regions)
               if regions else tp.get("регионы"))
        n_regions = len(regions)
    rows = cover_common.passport_rows(
        who=tp.get("группа"),
        geo=geo, geo_label=f"Регионы ({n_regions})" if n_regions else "Регионы",
        season=(tp.get("сезон") or fm.get("season")
                or _season_from_trip_id(fm.get("trip_id"))),
        tempo=tp.get("темп"),
    )
    dr_date = _format_dr_run_date(fm.get("dr_run_date"))
    if dr_date:
        rows.append(("Дата DR-прогона", dr_date))
    n_cards = extracted.get("total_cards") or fm.get("reports_count")
    if n_cards:
        crit = extracted.get("critical_count") or 0
        cards_text = f"{n_cards}" + (f" (critical: {crit})" if crit else "")
        rows.append(("Отчётов всего", cards_text))
    if extracted.get("warnings"):
        rows.append(("Предупреждений", str(len(extracted["warnings"]))))
    lang = _language_summary(extracted)
    if lang:
        rows.append(("Языки источников", lang))
    return rows


# ---------------------------------------------------------------------------
# Card → entity_card mapping
# ---------------------------------------------------------------------------


# Поля, которые НЕ выводятся вообще (по обсуждению с пользователем):
_FIELDS_DROP = {6, 8, 10, 16, 17}


def _build_card_meta_line(card: Card) -> str | None:
    """Meta-line карточки: `{platform·lang} · {автор} · {дата_публикации} · {когда поездка}`."""
    parts: list[str] = []
    plat = _fv(card.fields, 2)
    if plat and not _is_empty_value(plat):
        parts.append(_strip_md_bold(plat.strip()))
    author = _extract_author(_fv(card.fields, 3))
    if author:
        parts.append(author)
    pub_date = _fv(card.fields, 4)
    if pub_date and not _is_empty_value(pub_date):
        parts.append(_strip_md_bold(pub_date.strip()))
    trip_when = _fv(card.fields, 5)
    if trip_when and not _is_empty_value(trip_when):
        parts.append(_strip_md_bold(trip_when.strip()))
    return " · ".join(parts) if parts else None


def _build_card_bullets(card: Card) -> list[str]:
    """Body-bullets карточки. Поля 6/8/10/16/17 пропущены; пустые — пропущены."""
    bullets: list[str] = []

    # Покрытые регионы (из суффикса заголовка) — первой строкой. Регион здесь
    # справочный (группировки по регионам на Stage 1 нет — это свойство POI).
    if card.covered_regions:
        bullets.append(f"**Покрывает:** {', '.join(card.covered_regions)}")

    # Группа / стиль — одной строкой если оба заполнены.
    group = _fv(card.fields, 7)
    style = _fv(card.fields, 9)
    g_ok = group and not _is_empty_value(group)
    s_ok = style and not _is_empty_value(style)
    group_ru = _ru_field_value(7, _strip_md_bold(group).strip()) if g_ok else ""
    style_ru = _ru_field_value(9, _strip_md_bold(style).strip()) if s_ok else ""
    if g_ok and s_ok:
        bullets.append(f"**Группа / стиль:** {group_ru} · {style_ru}")
    elif g_ok:
        bullets.append(f"**Группа:** {group_ru}")
    elif s_ok:
        bullets.append(f"**Стиль:** {style_ru}")

    # Транспорт — режем длинные скобки-перечисления (авиалинии/тарифы) и
    # дедуплицируем повторы типов («тук-тук» х3 → один раз).
    tr = _fv(card.fields, 11)
    if tr and not _is_empty_value(tr):
        tr_cleaned = _clean_transport(_strip_md_bold(tr))
        if tr_cleaned and not _is_empty_value(tr_cleaned):
            bullets.append(f"**Транспорт:** {tr_cleaned.strip()}")

    # Размещение — только тип (отель / хостел / homestay / квартира / …),
    # имена конкретных отелей и описания не выводим. Если тип не извлечь —
    # bullet вообще не показывается (по согласованию с пользователем).
    acc = _fv(card.fields, 12)
    if acc and not _is_empty_value(acc):
        acc_type = _extract_accommodation_type(acc)
        if acc_type:
            bullets.append(f"**Размещение:** {acc_type}")

    # POI с тональностью — главное содержание.
    poi = _fv(card.fields, 14)
    if poi and not _is_empty_value(poi):
        bullets.append(f"**POI:** {_strip_md_bold(poi).strip()}")

    # Скрытые жемчужины — если есть, не «—»/«не упомянуто».
    gems = _fv(card.fields, 15)
    if gems and not _is_empty_value(gems):
        bullets.append(f"**Скрытые жемчужины:** {_strip_md_bold(gems).strip()}")

    # Главная рекомендация — цитата.
    rec = _fv(card.fields, 19)
    if rec and not _is_empty_value(rec):
        bullets.append(f"**Главное:** {_strip_md_bold(rec).strip()}")

    return bullets


def _build_card_side_badges(card: Card) -> list[tuple[str, str]]:
    """Side badges: tonality:critical, photo-focus, резидент. Подписи — из
    taxonomy (`report_tonality` / `flag_badge`), не хардкодом (firewall §7)."""
    out: list[tuple[str, str]] = []
    if card.is_critical:
        out.append((taxonomy.label("report_tonality", "critical"), COLORS["danger"]))
    if "photo" in card.flags:
        out.append((taxonomy.label("flag_badge", "photo"), COLORS["primary"]))
    if "residence" in card.flags:
        out.append((taxonomy.label("flag_badge", "residence"), COLORS["secondary"]))
    if "iconic" in card.flags:
        out.append((taxonomy.label("flag_badge", "iconic"), COLORS["primary"]))
    return out


def _build_card_block(card: Card, *, accent_color: str) -> list:
    """Возвращает список flowables: entity_card + опц. warning_box с жалобами.

    entity_card получает outline_level=0 (карточка — пункт верхнего уровня
    PDF outline'а); регионы в outline НЕ выводятся.
    """
    url, _ = _extract_url_and_title(_fv(card.fields, 1))
    title = _card_visible_title(card)
    meta_line = _build_card_meta_line(card)
    bullets = _build_card_bullets(card)
    side = _build_card_side_badges(card)

    badge_color = _focus_color(card.focus_tag) if not card.is_critical else COLORS["danger"]
    accent = COLORS["danger"] if card.is_critical else accent_color

    tbl = pdf_lib.entity_card(
        title=title,
        accent_color=accent,
        badge=(card.focus_tag, badge_color),
        meta_line=meta_line,
        body_bullets=bullets or None,
        side_badges=side or None,
        title_link=url,
        anchor_slug=_card_slug(card.num),
    )
    # Добавляем outline entry на карточку (entity_card не выставляет outline_level).
    tbl._outline_level = 0          # type: ignore[attr-defined]
    tbl._outline_title = _card_outline_title(card)  # type: ignore[attr-defined]

    out: list = [tbl]

    # Жалобы критической карточки — отдельным warning_box под карточкой.
    if card.is_critical:
        complaint = _fv(card.fields, 18)
        if complaint and not _is_empty_value(complaint):
            # Срезаем дублирующий префикс «tonality: critical:» если есть.
            txt = re.sub(r"^\s*(?:жалобы\s*(?:/\s*tonality:\s*critical)?\s*[:.]?\s*)",
                         "", complaint, flags=re.IGNORECASE).strip()
            txt = _strip_md_bold(txt)
            out.append(pdf_lib.spacer(2))
            out.append(pdf_lib.warning_box(f"Жалобы: {txt}", pdf_lib.get_styles()))

    out.append(pdf_lib.spacer(8))
    return out


# ---------------------------------------------------------------------------
# Сводная таблица «Покрытие по регионам»
# ---------------------------------------------------------------------------


def _coverage_table_rows(extracted: dict) -> list[list[str]]:
    """Строки таблицы покрытия: Регион | Карточек | POI-критика | Critical-карточек.

    Critical-карточки считаются по нашей extract_content классификации (детектится
    из маркеров/inline/grep field 18); POI-критика per region — из ## POI-критика
    блока META, если есть.
    """
    cards = extracted.get("cards")
    if cards is None:
        cards = [c for r in (extracted.get("regions") or []) for c in r.cards]
    meta = extracted.get("meta") or {}
    crit_map: dict[str, str] = {}
    for region, count in meta.get("poi_critique_per_region", []):
        crit_map[region.lower().strip()] = count

    # Агрегируем по ПОКРЫТЫМ регионам (из суффиксов карточек), а не по
    # группировке (её больше нет). Регион → [сколько отчётов, из них critical].
    agg: dict[str, list[int]] = {}
    order: list[str] = []
    for c in cards:
        for rg in c.covered_regions:
            if rg not in agg:
                agg[rg] = [0, 0]
                order.append(rg)
            agg[rg][0] += 1
            if c.is_critical:
                agg[rg][1] += 1

    rows: list[list[str]] = [["Регион", "Отчётов", "POI-критика (META)",
                              taxonomy.label("report_tonality", "critical")]]
    if not agg:
        n_crit = sum(1 for c in cards if c.is_critical)
        rows.append(["Все отчёты", str(len(cards)), "—",
                     str(n_crit) if n_crit else "—"])
        return rows
    for rg in order:
        n_cards, n_critical = agg[rg]
        short = rg.split("(")[0].lower().strip().rstrip(",")
        meta_crit = ""
        for key, val in crit_map.items():
            if key in short or short in key:
                meta_crit = val
                break
        rows.append([rg, str(n_cards), meta_crit or "—",
                     str(n_critical) if n_critical else "—"])
    return rows


# ---------------------------------------------------------------------------
# Build PDF
# ---------------------------------------------------------------------------


def build_pdf(extracted: dict, output_path: str | Path, *, recipient: str = "self") -> str:
    """Собрать PDF Stage 1 из извлечённой структуры."""
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 1 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    styles = pdf_lib.get_styles()

    # Карта section_anchors для inline-ссылок «[имя](#region-3-…)» в md.
    anchors: dict[str, str] = {}
    for r in extracted.get("regions") or []:
        anchors[r.name] = r.slug
        anchors[r.name.split("(")[0].strip().rstrip(",")] = r.slug
    pdf_lib.set_section_anchors(anchors)

    doc = pdf_lib.make_doc(
        output_path,
        orientation="portrait",
        title=f"DR-база — {extracted['frontmatter'].get('trip_id', '')}",
    )
    created = extracted['frontmatter'].get('created') or _dt.date.today().isoformat()
    pdf_lib.set_footer_text(f"создан {created}".strip())

    try:
        story: list[Any] = []

        # ─── 1. Cover ───────────────────────────────────────────────────
        story.append(pdf_lib.heading_paragraph(
            _cover_title(extracted), styles["cover_title"],
        ))
        sub = _cover_subtitle(extracted)
        if sub:
            story.append(pdf_lib.para(sub, styles["cover_subtitle"]))
        story.append(pdf_lib.spacer(14))
        kp_rows = _cover_key_params(extracted)
        if kp_rows:
            story.append(pdf_lib.key_params_table(kp_rows))

        # Mode B: sample_curation_note — info-box про добавленные карточки.
        note = extracted.get("sample_curation_note")
        if note:
            story.append(pdf_lib.spacer(10))
            if isinstance(note, list):
                note_text = " · ".join(str(n).strip() for n in note if n)
            else:
                note_text = str(note).strip()
            note_text = _strip_pipeline_script_ref(note_text)
            if note_text:
                story.append(pdf_lib.info_box(
                    f"**Расширение выборки:** {note_text}", styles,
                ))

        # ─── 2. Сводка META-DIAGNOSTICS ─────────────────────────────────
        meta = extracted.get("meta") or {}
        has_meta = bool(meta) or extracted.get("warnings")
        if has_meta:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Сводка отчётов",
                anchor_slug="meta-summary",
                outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))

            # 2.1 Таблица покрытия — Регион | Карточек | POI-критика | critical.
            regions = extracted.get("regions") or []
            if regions:
                rows = _coverage_table_rows(extracted)
                story.append(pdf_lib.para("Покрытие по регионам", styles["h3"],
                                          highlight_todo=False))
                story.append(pdf_lib.data_table(
                    rows, header=True,
                    # «Карточек» при 13% переносился («Карточ⏎ек») — даём 16%
                    # за счёт колонки «Регион».
                    col_widths=["42%", "16%", "27%", "15%"],
                ))
                story.append(pdf_lib.spacer(8))

            # 2.2 Распределения — локализуем english-термины (backpacker →
            # бэкпэкер и т.д.) перед выводом.
            dist = meta.get("distributions") or {}
            if dist:
                story.append(pdf_lib.para("Распределения", styles["h3"],
                                          highlight_todo=False))
                for name, items in dist.items():
                    story.append(pdf_lib.para(
                        f"**По {name}:**", styles["body"], highlight_todo=False,
                    ))
                    localized = [_ru_style(it) for it in items]
                    story.extend(pdf_lib.bullet_list(localized, styles))
                    story.append(pdf_lib.spacer(2))

            # 2.3 Предупреждения — один warning_box с bullet-list'ом
            # (не N отдельных box'ов). Префиксы «WARN-N:» / «B1-awd.ru:» /
            # «NOTE:» срезаются — карточка сама даёт визуальный сигнал
            # «предупреждение», номер пайплайн-уровневый и пользователю
            # не нужен. Дедуп смысловых повторов — задача polish T9.
            warns = extracted.get("warnings") or []
            cleaned_warns = [c for c in (_clean_warning_text(str(w)) for w in warns) if c]
            if cleaned_warns:
                story.append(pdf_lib.spacer(6))
                story.append(pdf_lib.para("Предупреждения", styles["h3"],
                                          highlight_todo=False))
                story.append(pdf_lib.warning_box_bullets(cleaned_warns, styles))

        # ─── 3. Карточки по регионам ────────────────────────────────────
        regions = extracted.get("regions") or []
        for r in regions:
            if not r.cards:
                continue
            color = REGION_PALETTE[(r.idx - 1) % len(REGION_PALETTE)]
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                f"{r.name} · {len(r.cards)} {_plural_cards(len(r.cards))}",
                bg_color=color,
                anchor_slug=r.slug,
                # Регионы в outline НЕ выводим — outline по картам.
                outline_level=None,
            ))
            story.append(pdf_lib.spacer(8))
            for card in r.cards:
                story.extend(_build_card_block(card, accent_color=color))

        # ─── 4. Tails ────────────────────────────────────────────────────
        if meta.get("season_caveat"):
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Сезонные caveat'ы",
                anchor_slug="season-caveats",
                outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            story.append(pdf_lib.info_box(meta["season_caveat"], styles))

        if meta.get("sources_outside_seed"):
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Источники вне seed-списка",
                anchor_slug="sources-outside-seed",
                outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            story.extend(pdf_lib.bullet_list(meta["sources_outside_seed"], styles))

        if meta.get("sources_tried"):
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Источники, что пробовали",
                anchor_slug="sources-tried",
                outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            story.extend(pdf_lib.bullet_list(meta["sources_tried"], styles))

        pdf_lib.build_doc(doc, story, with_background=True)
        return str(output_path)
    finally:
        pdf_lib.set_footer_text("")
        pdf_lib.clear_section_anchors()


def _plural_cards(n: int) -> str:
    """N → «карточек / карточка / карточки» по русскому plural."""
    if n % 10 == 1 and n % 100 != 11:
        return "карточка"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "карточки"
    return "карточек"


# ---------------------------------------------------------------------------
# Renderer entry point + регистрация
# ---------------------------------------------------------------------------


def render_stage1(
    parsed: dict,
    *,
    recipient: str = "self",
    output_path: str | Path,
    **_kw: Any,
) -> "_renderer.RenderRequest":
    """Главный entry-point: распарсенный 1_dr_reports → PDF + RenderRequest."""
    extracted = extract_content(
        parsed, input_path=[_kw.get("source_file"), output_path])
    pdf_path = build_pdf(extracted, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage":          "1_dr_reports",
            "trip_id":        parsed.get("trip_id"),
            "recipient":      recipient,
            "regions_count":  len(extracted["regions"]),
            "cards_count":    extracted["total_cards"],
            "critical_count": extracted["critical_count"],
        },
        metadata={
            "trip_id":     parsed.get("trip_id"),
            "stage":       parsed.get("stage"),
            "recipient":   recipient,
            "font_family": pdf_lib._ACTIVE_FAMILY,
        },
        notes=[],
    )


# Регистрация — два ключа на случай отсутствия YAML (тогда engine fallback
# на f"{args.stage}_stage" = "1_stage").
_renderer.register_renderer("1_dr_reports", "pdf", render_stage1)
_renderer.register_renderer("1_stage", "pdf", render_stage1)

"""stages/stage4.py — экстрактор контента + PDF builder для Stage 4.

**Контракт формата** артефакта (8 осей сравнит. таблицы, `## Решение`, YAML) —
канон `references/stage4/stage4-output-spec.md`; сверка — `tests/test_format_contract.py`.

Stage 4 — варианты маршрута. PDF (self) — read-only витрина сравнения:
пользователь открывает 2–3 варианта, сравнивает по сводной таблице,
выбирает один в чате. Решение в файле НЕ фиксируется (блок `## Решение`
из markdown не рендерится).

Структура PDF (portrait A4):
  1. Обложка — заголовок + рекомендованный сбалансированный вариант + key-params.
  2. Контекст + предупреждения/допущения.
  3. Сравнение вариантов — сводная таблица + навигация-ссылки на варианты.
  4. Приоритеты POI — свёрнуто (что обязательно / условно / исключено).
  5. Варианты A/B/C — каждый цветной section_bar (REGION_PALETTE),
     в outline level 1; таблица дней, что включает/отбрасывает, логистика,
     риски, кому подходит; back-link «↑ К сравнению».
  6. Honest assessment.

Все визуальные блоки — из pdf_lib. Stage-модуль только извлекает контент
и компонует готовые компоненты (см. pdf-visual-language.md §9).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Импорт соседних модулей пакета — поддерживаем оба режима запуска.
if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from export import adapter as _adapter   # type: ignore[no-redef]
    from export import pdf_lib                # type: ignore[no-redef]
    from export import renderer as _renderer  # type: ignore[no-redef]
    from export import cover_common            # type: ignore[no-redef]
    from export import travelers as _travelers  # type: ignore[no-redef]
    from export.style import REGION_PALETTE   # type: ignore[no-redef]
else:
    from .. import adapter as _adapter
    from .. import pdf_lib
    from .. import renderer as _renderer
    from .. import cover_common
    from .. import travelers as _travelers
    from ..style import REGION_PALETTE


# ---------------------------------------------------------------------------
# Markdown helpers (общие для всех body-секций Stage 4)
# ---------------------------------------------------------------------------

_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$")
_HR_RE = re.compile(r"^-{3,}\s*$")
# Sub-header — одиночная bold-строка `**Что-то:**` (без текста после).
_SUB_HEADER_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*\s*[:.]?\s*$")
# Field-строка `**Label:** value` (параметры варианта). Лейбл в начале строки
# жирным с двоеточием внутри `**…:**`; значение может быть и пустым (caption).
_FIELD_LINE_RE = re.compile(r"^\s*\*\*[^*\n]+?:\*\*")
# Warning-лид: блок начинается с ⚠️/⚠ — рендерится целиком в warning_box.
_WARNING_LEAD_RE = re.compile(r"^\s*⚠️?\s*(.+)$", re.DOTALL)


def _split_md_blocks(text: str) -> list[list[str]]:
    """Разбить markdown на блоки по пустым строкам."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for ln in text.splitlines():
        if ln.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        blocks.append(current)
    return blocks


def _split_md_row(line: str) -> list[str]:
    """Разбить ряд markdown-таблицы на ячейки."""
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _is_table_block(block: list[str]) -> bool:
    return len(block) >= 2 and "|" in block[0] and bool(_TABLE_DELIM_RE.match(block[1]))


def _table_rows(block: list[str]) -> list[list[str]]:
    """Ряды GFM-таблицы (без строки-разделителя), нормированные под header."""
    rows = [_split_md_row(l) for l in block if "|" in l and not _TABLE_DELIM_RE.match(l)]
    if not rows:
        return rows
    ncols = len(rows[0])
    return [r + [""] * (ncols - len(r)) for r in rows]


def _is_bullet_block(block: list[str]) -> bool:
    has_bullet = False
    for ln in block:
        if not ln.strip():
            continue
        stripped = ln.lstrip()
        if stripped.startswith("- "):
            has_bullet = True
        elif not (ln.startswith(" ") or ln.startswith("\t")):
            return False
    return has_bullet


def _parse_bullets(block: list[str]) -> list[str]:
    """Достать пункты bullet-блока, склеив multi-line items."""
    items: list[str] = []
    current: list[str] = []
    for ln in block:
        stripped = ln.lstrip()
        if stripped.startswith("- "):
            if current:
                items.append(" ".join(s.strip() for s in current))
            current = [stripped[2:]]
        else:
            current.append(ln.strip())
    if current:
        items.append(" ".join(s.strip() for s in current))
    return items


def _extract_first_table(body: str) -> list[list[str]] | None:
    """Найти первую GFM-таблицу в body и вернуть её ряды (header в [0])."""
    for block in _split_md_blocks(body):
        if _is_table_block(block):
            return _table_rows(block)
    return None


def render_md_body(
    story, body: str, styles, *, table_col_widths: list | None = None,
) -> None:
    """Рендер markdown-body Stage 4: параграфы / bullets / таблицы / warning.

    Блоки:
      - `⚠️ ...` / `⚠ ...` в начале → warning_box (amber).
      - GFM-таблица → data_table.
      - одиночная bold-строка `**X:**` → подзаголовок h4.
      - bullet-блок → bullet_list (inline bold сохраняется).
      - `---` → пропуск (роль разрыва выполняют page break'и).
      - иначе → параграф body.
    """
    if not body or not body.strip():
        return
    body = _linkify_variants(body)
    for block in _split_md_blocks(body):
        if not block:
            continue
        if all(_HR_RE.match(ln) or not ln.strip() for ln in block):
            continue
        first = block[0]

        # Warning-лид (бюджетный блок варианта, сезонные предупреждения).
        if first.lstrip().startswith("⚠"):
            m = _WARNING_LEAD_RE.match(" ".join(ln.strip() for ln in block))
            text = m.group(1).strip() if m else " ".join(ln.strip() for ln in block)
            story.append(pdf_lib.warning_box(text, styles))
            story.append(pdf_lib.spacer(4))
            continue

        # GFM-таблица.
        if _is_table_block(block):
            story.append(pdf_lib.spacer(2))
            story.append(pdf_lib.data_table(
                _table_rows(block), header=True, col_widths=table_col_widths,
            ))
            story.append(pdf_lib.spacer(6))
            continue

        # H4 (`#### `).
        if first.startswith("#### "):
            story.append(pdf_lib.para(first[5:].strip(), styles["h4"]))
            if block[1:]:
                render_md_body(story, "\n".join(block[1:]), styles)
            continue

        # Подзаголовок — одиночная bold-строка.
        if len([ln for ln in block if ln.strip()]) == 1 and _SUB_HEADER_RE.match(first):
            cleaned = re.sub(r"^\*\*|\*\*\s*:?\s*$|:\s*$", "", first.strip()).replace("**", "")
            story.append(pdf_lib.para(cleaned, styles["h4"], highlight_todo=False))
            continue

        # Bullet-список.
        if _is_bullet_block(block):
            items = _parse_bullets(block)
            if items:
                story.extend(pdf_lib.bullet_list(items, styles))
            continue

        # Блок field-строк `**Label:** value` (параметры варианта: Регионы /
        # Темп / Ценовой уровень / Open-jaw / Транспорт) — каждую с новой
        # строки, не склеивать в один абзац (markdown soft-wrap иначе сливает).
        nonblank = [ln for ln in block if ln.strip()]
        if len(nonblank) >= 2 and all(_FIELD_LINE_RE.match(ln) for ln in nonblank):
            for ln in nonblank:
                story.append(pdf_lib.para(
                    ln.strip(), styles["body"], highlight_todo=False))
            continue

        # Параграф.
        story.append(pdf_lib.para(" ".join(ln.strip() for ln in block), styles["body"]))


# ---------------------------------------------------------------------------
# Извлечение структуры
# ---------------------------------------------------------------------------

# Заголовок варианта — оба формата: «Вариант A: …» (новый) и
# «Variant A — …» (старый). Метка = первый токен после слова, затем
# опциональный разделитель (: / — / – / -), затем человекочитаемый заголовок.
_VARIANT_RE = re.compile(
    r"^(?:Вариант|Variant)\s+([^\s:—–-]+)\s*[:—–-]?\s*(.*)$", re.IGNORECASE,
)
# H2-секции, которые НЕ являются вариантами и обрабатываются отдельно.
_CONTEXT_H2 = "Контекст для следующих стадий"
_PRIORITY_H2 = "Priority pool"
_HONEST_H2 = "Honest assessment"
_DECISION_H2 = "Решение"   # НЕ рендерится
# Комментарии пользователя к вариантам (заполняет пользователь — руками в md
# или полем в HTML; потребляет Stage 5). Строки секции:
#   `**Вариант A:** текст` — к варианту; `**Общий комментарий:** текст` — ко всему.
# Метка намеренно без «Комментарий пользователя» (у Stage 3 это счётчик POI).
_COMMENTS_H2 = "Комментарии к вариантам"
_GENERAL_COMMENT_LABEL = "Общий комментарий"
_COMMENT_LINE_RE = re.compile(
    r"^([ \t]*(?:[-*][ \t]+)?\*\*(?:(?:Вариант|Variant)[ \t]+([^\s:*]+)|Общий комментарий):\*\*[ \t]*)(.*?)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
# Pipeline/handoff-секции — не показываем (polish их обычно убирает; при
# raw-рендере подавляем здесь, чтобы не зашумлять витрину).
_SKIP_H2 = {
    "Tags resolution", "Trip parameters", "Следующий шаг",
    "Priority pool",  # обрабатывается отдельной свёрткой
}


def _is_comparison_h2(heading: str) -> bool:
    """«Сравнительная таблица» (новый) / «Сравнение» (старый формат)."""
    return heading.strip().lower().startswith("сравн")


_MONTHS_RU = {
    "01": "январь", "02": "февраль", "03": "март", "04": "апрель",
    "05": "май", "06": "июнь", "07": "июль", "08": "август",
    "09": "сентябрь", "10": "октябрь", "11": "ноябрь", "12": "декабрь",
}


def _humanize_regions(trip_id: str, *, join: str = ", ") -> str:
    """Регион-часть trip_id → человекочитаемо: `камбоджа_лаос` → «Камбоджа, Лаос»;
    `вьетнам_север_…` → «Северный Вьетнам».

    Fallback, когда polish не дал маркер `регионы`. Без стрелок (порядок
    маршрута из trip_id неизвестен — стрелки подразумевали бы его ошибочно).
    """
    return cover_common.humanize_trip_geo(trip_id, join=join, default="")


def _season_from_trip_id(trip_id: str) -> str | None:
    """`…_2026-02` → «февраль 2026» (fallback для поля «Сезон»)."""
    m = re.search(r"_(\d{4})-(\d{2})$", trip_id or "")
    if not m:
        return None
    name = _MONTHS_RU.get(m.group(2))
    return f"{name} {m.group(1)}" if name else None


# Маркер параметров поездки, который polish вставляет в начало body
# (по аналогии с region-маркерами Stage 5). Скрипт собирает из него
# таблицу ключевых параметров на обложке. Пример:
#   [[поездка: группа: родители (Алексей и Мария) | регионы: Камбоджа → Лаос |
#    старт: Пномпень | финиш: Луангпрабанг | темп: размеренный]]
_TRIP_MARKER_RE = re.compile(r"\[\[\s*поездка:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)


def _parse_trip_marker(body: str) -> dict:
    """Распарсить `[[поездка: k: v | k: v]]` в dict (ключи в нижнем регистре)."""
    m = _TRIP_MARKER_RE.search(body or "")
    if not m:
        return {}
    out: dict = {}
    for part in m.group(1).split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _ru_variant_label(text: str) -> str:
    """`Variant A` / `Вариант A` → «Вариант A» (нормализация колонок сравнения)."""
    m = re.match(r"^(?:Вариант|Variant)\s+(.+)$", text.strip(), re.IGNORECASE)
    return f"Вариант {m.group(1)}" if m else text


# Точечная русификация заголовков секций (CONTESTED / английское «variant»).
_HEADING_FIXES = [
    (re.compile(r"\bCONTESTED\b", re.IGNORECASE), "Спорные"),
    (re.compile(r"\bvariants\b", re.IGNORECASE), "варианты"),
    (re.compile(r"\bvariant\b", re.IGNORECASE), "вариант"),
]


def _normalize_heading(h: str) -> str:
    for pat, repl in _HEADING_FIXES:
        h = pat.sub(repl, h)
    return h


# ---------------------------------------------------------------------------
# Линкификация упоминаний «Вариант X» в теле документа
# ---------------------------------------------------------------------------

# Карта «буква варианта» → slug (например, `A` → `variant-1`). Заполняется
# `_set_variant_link_map` в начале `build_pdf`, чистится в конце.
_VARIANT_LINK_MAP: dict[str, str] = {}


def _set_variant_link_map(m: dict[str, str]) -> None:
    global _VARIANT_LINK_MAP
    _VARIANT_LINK_MAP = dict(m)


def _clear_variant_link_map() -> None:
    global _VARIANT_LINK_MAP
    _VARIANT_LINK_MAP = {}


# Упоминания «Вариант A» / «варианта B» / «Variant C» — слово + одиночная
# буква. Поддерживаются падежи (вариант/варианта/варианту/варианте).
_VARIANT_INLINE_RE = re.compile(
    r"\b([Вв]ариант(?:[ауе])?|[Vv]ariant)\s+([A-ZА-Яa-zа-я])\b"
)
_MD_LINK_SPAN_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_CODE_SPAN_RE = re.compile(r"`[^`]+`")


def _linkify_variants(text: str) -> str:
    """Сделать упоминания «Вариант X» кликабельными ссылками на секцию варианта.

    Работает на markdown-уровне: оборачивает совпадения в `[…](#variant-N)`,
    которые затем `md_inline_to_rl` развернёт в реальные anchor-ссылки PDF.
    Уже существующие markdown-ссылки и code-спаны не трогаются.
    Карта букв задаётся `_set_variant_link_map`; если она пуста — no-op.
    """
    if not text or not _VARIANT_LINK_MAP:
        return text
    masks: list[str] = []

    def _mask(m: "re.Match[str]") -> str:
        masks.append(m.group(0))
        return f"\x00VLK{len(masks) - 1}\x00"

    text = _MD_LINK_SPAN_RE.sub(_mask, text)
    text = _CODE_SPAN_RE.sub(_mask, text)

    def _sub(m: "re.Match[str]") -> str:
        word, letter = m.group(1), m.group(2)
        slug = _VARIANT_LINK_MAP.get(letter.upper())
        if not slug:
            return m.group(0)
        # Английское «Variant»/«variant» русифицируем в отображаемом тексте.
        if word.lower() == "variant":
            word = "Вариант" if word[0].isupper() else "вариант"
        return f"[{word} {letter}](#{slug})"

    text = _VARIANT_INLINE_RE.sub(_sub, text)
    return re.sub(r"\x00VLK(\d+)\x00", lambda m: masks[int(m.group(1))], text)


@dataclass
class Variant:
    """Один вариант маршрута."""
    letter: str                 # отображаемая метка (A/B/C/А/Б/В)
    title: str                  # заголовок после «Вариант X:»
    intro: str                  # текст до первого H3 (бюджет + ночи)
    subsections: list[dict] = field(default_factory=list)  # [{heading, body}]
    user_comment: str = ""      # из `## Комментарии к вариантам` (`**Вариант X:** …`)


@dataclass
class PriorityBucket:
    """Одна корзина Priority pool (свёрнутая)."""
    label: str                  # человекочитаемая метка
    count: int                  # число позиций
    names: list[str] = field(default_factory=list)  # имена (для MUST/CONDITIONAL)


# Маппинг H3-заголовка Priority pool → (порядок, человекочитаемая метка,
# показывать ли имена). Сопоставление по префиксу заголовка.
_BUCKET_MAP = [
    ("MUST",        (1, "Обязательно (сильный сигнал)", True)),
    ("CONDITIONAL", (2, "Условно (по обстоятельствам)", True)),
    ("MEDIUM",      (3, "Средний приоритет", False)),
    ("Мягк",        (4, "Мягкие / погодно-резервные", False)),
    ("EXCLUDE",     (5, "Исключено", False)),
]


def _bucket_for(heading: str) -> tuple[int, str, bool] | None:
    for prefix, meta in _BUCKET_MAP:
        if heading.strip().upper().startswith(prefix.upper()):
            return meta
    return None


def _poi_names_from_table(rows: list[list[str]]) -> list[str]:
    """Имена POI из таблицы Priority pool (колонка после `#`).

    Header вида `| # | POI | ... |` → имена в колонке index 1. Если структура
    иная — берём вторую колонку как наиболее вероятную; пусто → [].
    """
    if not rows or len(rows) < 2:
        return []
    col = 1 if len(rows[0]) > 1 else 0
    names = []
    for r in rows[1:]:
        if col < len(r) and r[col].strip():
            # Убрать markdown-разметку из имени.
            name = re.sub(r"[*`]", "", r[col]).strip()
            if name:
                names.append(name)
    return names


def extract_content(parsed: dict, *, input_path: "Path | None" = None) -> dict:
    """Извлечь структуру для PDF-builder'а из распарсенного 4_variants.md.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10)."""
    sections = parsed.get("sections") or []
    fm = parsed.get("frontmatter") or {}
    trip_params = _parse_trip_marker(parsed.get("body") or "")
    resolved_who = _travelers.resolve_travelers(fm, trip_params, input_path)
    if resolved_who:
        trip_params["группа"] = resolved_who

    out: dict[str, Any] = {
        "title": parsed.get("title"),
        "frontmatter": fm,
        "warnings": list(fm.get("warnings") or []),
        "cover": _build_cover(parsed),
        "trip_params": trip_params,
        "context": None,
        "priority_buckets": [],
        "comparison_rows": None,
        "variants": [],
        "extras": [],
        "honest": None,
        "general_comment": "",
    }
    variant_comments: dict[str, str] = {}

    for sec in sections:
        h = sec["heading"]
        if h == _CONTEXT_H2:
            out["context"] = sec["body"]
        elif h == _PRIORITY_H2:
            out["priority_buckets"] = _collapse_priority(sec)
        elif _is_comparison_h2(h):
            out["comparison_rows"] = _extract_first_table(sec["body"])
        elif h == _HONEST_H2:
            out["honest"] = sec["body"]
        elif h == _DECISION_H2:
            continue  # read-only витрина: решение не рендерим
        elif h == _COMMENTS_H2:
            gen, per = parse_user_comments(sec["body"])
            out["general_comment"] = gen
            variant_comments.update(per)
        elif _VARIANT_RE.match(h):
            m = _VARIANT_RE.match(h)
            out["variants"].append(Variant(
                letter=m.group(1).strip(),
                title=m.group(2).strip(),
                intro=sec["body"],
                subsections=[
                    {"heading": ss["heading"], "body": ss["body"]}
                    for ss in sec.get("subsections", [])
                ],
            ))
        elif h in _SKIP_H2:
            continue  # pipeline/handoff-шум
        else:
            # Прочие содержательные H2 (CONTESTED решения, «Что не вошло …»):
            # graceful passthrough, чтобы не терять контент (export-design §6).
            out["extras"].append({"heading": h, "body": sec["body"]})

    for v in out["variants"]:
        v.user_comment = variant_comments.get(_comment_key(v.letter), "")
    return out


def _comment_key(letter: str) -> str:
    """Ключ сопоставления варианта и строки комментария: буква в верхнем
    регистре (`a`/`A` → `A`; кириллица остаётся кириллицей)."""
    return (letter or "").strip()[:1].upper()


def parse_user_comments(body: str) -> tuple[str, dict[str, str]]:
    """Секция `## Комментарии к вариантам` → (общий, {буква → текст}).

    Пустые значения пропускаются; при повторе строки берётся первая (как у
    edit-слоя HTML — он правит первую найденную)."""
    general, per = "", {}
    for m in _COMMENT_LINE_RE.finditer(body or ""):
        text = m.group(3).strip()
        if not text:
            continue
        if m.group(2):
            per.setdefault(_comment_key(m.group(2)), text)
        elif not general:
            general = text
    return general, per


def _collapse_priority(sec: dict) -> list[PriorityBucket]:
    """Свернуть Priority pool в список корзин (метка + count + имена)."""
    buckets: list[tuple[int, PriorityBucket]] = []
    for ss in sec.get("subsections", []):
        meta = _bucket_for(ss["heading"])
        if not meta:
            continue
        order, label, show_names = meta
        rows = _extract_first_table(ss["body"])
        count = max(len(rows) - 1, 0) if rows else 0
        names = _poi_names_from_table(rows) if (show_names and rows) else []
        if count == 0 and not names:
            continue
        buckets.append((order, PriorityBucket(label=label, count=count, names=names)))
    buckets.sort(key=lambda x: x[0])
    return [b for _, b in buckets]


def _build_cover(parsed: dict) -> dict:
    fm = parsed.get("frontmatter") or {}
    return {
        "trip_id": fm.get("trip_id") or "",
        "duration_nights": fm.get("duration_nights"),
        "variants_count": fm.get("variants_count"),
        "recommended_balanced": fm.get("recommended_balanced"),
        "budget_target_rub": fm.get("budget_target_rub"),
        "budget_status_overall": fm.get("budget_status_overall"),
        "created": fm.get("created"),
    }


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

_TEMPO_RE = re.compile(
    r"темп[ауе]?\s*[:—-]?\s*([A-Za-zА-Яа-я]+(?:\s*\([^)]*\))?)", re.IGNORECASE,
)


def _variant_display(raw: str) -> str:
    """`вариант_а` / `A` → «Вариант А» (первая буква заглавная)."""
    s = str(raw).replace("вариант_", "").replace("_", " ").strip()
    return "Вариант " + (s[:1].upper() + s[1:] if s else s)


def _cover_title(extracted: dict) -> str:
    """Человекочитаемый заголовок обложки.

    Если polish дал чистый H1 — используем его. Если H1 — pipeline-жаргон
    («Stage 4 … — Варианты маршрута: trip_id»), собираем сами:
    «{регионы} · {N} ночей · сравнение вариантов».
    """
    raw = (extracted.get("title") or "").strip()
    if raw and not re.search(r"stage|variants|варианты\s+маршрута\s*:", raw, re.IGNORECASE):
        return raw
    cover = extracted["cover"]
    tp = extracted.get("trip_params") or {}
    regions = tp.get("регионы") or _humanize_regions(cover.get("trip_id") or "")
    # Регионы — в заголовке; длительность/сезон/темп — в таблице ниже
    # (чтобы не дублировать одно и то же дважды).
    return f"{regions} · сравнение вариантов" if regions else "Сравнение вариантов маршрута"


def _build_cover_page(story, extracted: dict, styles) -> None:
    """Обложка: заголовок (в outline как «Обзор») + таблица параметров поездки."""
    cover = extracted["cover"]
    tp = extracted.get("trip_params") or {}
    title_p = pdf_lib.para(_cover_title(extracted), styles["cover_title"])
    title_p._dest_slug = "top"            # type: ignore[attr-defined]
    title_p._outline_title = "Обзор"      # type: ignore[attr-defined]
    title_p._outline_level = 0            # type: ignore[attr-defined]
    story.append(title_p)
    rec = cover.get("recommended_balanced")
    if rec:
        story.append(pdf_lib.para(
            f"Рекомендованный сбалансированный — {_variant_display(rec)}",
            styles["cover_subtitle"], highlight_todo=False,
        ))
    story.append(pdf_lib.spacer(8))

    tempo = tp.get("темп")
    if not tempo:
        m = _TEMPO_RE.search(extracted.get("context") or "")
        cand = m.group(1).strip() if m else None
        # Не путать «темпе и транспорте» → «и»: берём только реальный темп.
        tempo = cand if cover_common.looks_like_tempo(cand) else None
    # Маршрут (регионы) НЕ дублируем — он уже в заголовке обложки.
    start, finish = tp.get("старт"), tp.get("финиш")
    season = tp.get("сезон") or _season_from_trip_id(cover.get("trip_id") or "")
    n_variants = cover.get("variants_count") or len(extracted.get("variants") or [])

    # Старт/финиш: один город, если совпадают; два через стрелку, если разные.
    if start and finish and start.strip().lower() == finish.strip().lower():
        geo_label, geo = "Старт и финиш", start
    elif start and finish:
        geo_label, geo = "Старт / финиш", f"{start} → {finish}"
    else:
        geo_label, geo = "Регионы", None  # маршрут уже в заголовке обложки
    duration = f"{cover['duration_nights']} ночей" if cover.get("duration_nights") else None
    budget = (f"ориентир ≈{cover['budget_target_rub']:,} ₽".replace(",", " ")
              if cover.get("budget_target_rub") else None)
    rows = cover_common.passport_rows(
        who=tp.get("группа"), geo=geo, geo_label=geo_label,
        season=season, duration=duration, tempo=tempo, budget=budget,
    )
    if n_variants:
        rows.append(("Вариантов", f"{n_variants}"))
    story.append(pdf_lib.key_params_table(rows))


# Ключи вводных **Key:**-пунктов контекста, которые дублируют таблицу
# параметров на обложке (маршрут/длительность/сезон/темп/бюджет/группа).
# Такие пункты из прозы контекста вырезаются — чтобы не повторять дважды.
_CTX_DUP_KEYS = {
    "поездка", "маршрут", "регион", "регионы", "длительность", "ночей",
    "сезон", "сроки", "даты", "темп", "бюджет", "группа", "кто едет",
    "путешественник", "путешественники",
}
_CTX_BULLET_KEY_RE = re.compile(r"^\s*-\s+\*\*([^*]+?)\*\*\s*[:.]?", re.IGNORECASE)


def _strip_dup_context(body: str) -> str:
    """Убрать из контекста вводные **Key:**-пункты, дублирующие cover-таблицу.

    Работает на bullet-формате контекста (`- **Поездка:** …`, `- **Темп:** …`):
    такие пункты вырезаются вместе с их continuation-строками. Прочий контент
    (Жёсткое ограничение, Теги пользователя, логика) сохраняется. На
    прозовом контексте (без `- **Key:**` буллетов) — no-op.
    """
    lines = body.splitlines()
    out: list[str] = []
    skipping = False
    for ln in lines:
        m = _CTX_BULLET_KEY_RE.match(ln)
        if m:
            key = m.group(1).strip().lower().rstrip(":").strip()
            skipping = key in _CTX_DUP_KEYS
            if skipping:
                continue
        elif skipping and (ln.startswith(" ") or ln.startswith("\t")):
            continue  # continuation-строка вырезанного пункта
        else:
            skipping = False
        out.append(ln)
    return "\n".join(out).strip()


def build_pdf(extracted: dict, output_path: str | Path, *, recipient: str = "self") -> str:
    """Собрать PDF Stage 4 из извлечённой структуры."""
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 4 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    styles = pdf_lib.get_styles()
    doc = pdf_lib.make_doc(
        output_path,
        orientation="portrait",
        title=f"Варианты маршрута — {extracted['cover'].get('trip_id', '')}",
    )
    _created = extracted["cover"].get("created") or ""
    pdf_lib.set_footer_text(f"создан {_created}".strip() if _created else "")
    # Slug каждого варианта — по индексу (ASCII-safe независимо от алфавита метки).
    variants = extracted["variants"]
    variant_slugs = {id(v): f"variant-{i}" for i, v in enumerate(variants, start=1)}
    # Карта «буква → slug» для линкификации упоминаний «Вариант X» в теле.
    letter_map = {v.letter.strip().upper(): variant_slugs[id(v)] for v in variants if v.letter.strip()}
    _set_variant_link_map(letter_map)
    try:
        return _build_pdf_body(extracted, doc, styles, variants, variant_slugs, output_path)
    finally:
        _clear_variant_link_map()
        pdf_lib.set_footer_text("")


def _build_pdf_body(extracted, doc, styles, variants, variant_slugs, output_path) -> str:
    story: list[Any] = []

    # — Обложка —
    _build_cover_page(story, extracted, styles)

    # — Контекст — прозой прямо под обложкой (без page break). Пункты,
    #   дублирующие таблицу параметров (маршрут/длительность/сезон/темп/…),
    #   вырезаем, чтобы не повторять одно и то же дважды.
    if extracted["context"]:
        ctx = _strip_dup_context(extracted["context"])
        if ctx.strip():
            story.append(pdf_lib.spacer(10))
            render_md_body(story, ctx, styles)

    # — Предупреждения / допущения (self видит все) —
    if extracted["warnings"]:
        story.append(pdf_lib.spacer(6))
        story.append(pdf_lib.para("Предупреждения и допущения", styles["h4"],
                                  highlight_todo=False))
        story.extend(pdf_lib.bullet_list(extracted["warnings"], styles))

    # — Сравнение вариантов (сводная таблица сверху + навигация) —
    if extracted["comparison_rows"]:
        story.append(pdf_lib.page_break())
        story.append(pdf_lib.heading_paragraph(
            "Сравнение вариантов", styles["h2"],
            anchor_slug="comparison", outline_level=0,
        ))
        # Навигация: ссылки на секции вариантов (видимы на белом, в отличие
        # от ссылок в шапке таблицы — там фон = primary, ссылка слилась бы).
        if variants:
            nav = " · ".join(
                f"[{_variant_display(v.letter)}](#{variant_slugs[id(v)]})"
                for v in variants
            )
            story.append(pdf_lib.para(f"Подробнее по вариантам: {nav}",
                                      styles["small"], highlight_todo=False))
            story.append(pdf_lib.spacer(4))
        # Русифицируем заголовки колонок («Variant A» → «Вариант A») и
        # линкифицируем упоминания «Вариант X» в data-ячейках.
        rows = [list(r) for r in extracted["comparison_rows"]]
        rows[0] = [_ru_variant_label(c) for c in rows[0]]
        for i in range(1, len(rows)):
            rows[i] = [_linkify_variants(c) for c in rows[i]]
        ncols = len(rows[0])
        # Первая колонка (ось) уже, остальные (варианты) — поровну.
        widths = (["22%"] + [f"{78 // (ncols - 1)}%"] * (ncols - 1)) if ncols > 1 else None
        story.append(pdf_lib.data_table(rows, header=True, col_widths=widths))

    # — Приоритеты POI (свёрнуто) —
    if extracted["priority_buckets"]:
        story.append(pdf_lib.spacer(10))
        story.append(pdf_lib.para("Приоритеты POI", styles["h3"], highlight_todo=False))
        story.append(pdf_lib.info_box(
            "Пользовательский комментарий перекрывает методологическую "
            "категорию. Полные таблицы — в рабочем файле стадии.", styles,
        ))
        story.append(pdf_lib.spacer(4))
        pairs: list[tuple[str, str]] = []
        for b in extracted["priority_buckets"]:
            if b.names:
                val = ", ".join(b.names)
            else:
                val = f"{b.count} поз." if b.count else "—"
            pairs.append((b.label, val))
        story.extend(pdf_lib.definition_list(pairs, styles["body"]))

    # — Варианты — каждый вариант сам по себе секция в оглавлении (level 0);
    #   отдельной родительской «Варианты маршрута» в outline нет.
    for i, v in enumerate(variants, start=1):
        story.append(pdf_lib.page_break())
        _render_variant(story, v, styles, slug=variant_slugs[id(v)],
                        color=REGION_PALETTE[(i - 1) % len(REGION_PALETTE)],
                        has_comparison=bool(extracted["comparison_rows"]))

    # — Прочие содержательные секции (Спорные решения, «Что не вошло …») —
    for ei, ex in enumerate(extracted["extras"], start=1):
        story.append(pdf_lib.page_break())
        story.append(pdf_lib.section_bar(
            _normalize_heading(ex["heading"]), anchor_slug=f"extra-{ei}", outline_level=0,
        ))
        story.append(pdf_lib.spacer(4))
        render_md_body(story, ex["body"], styles)

    # — Honest assessment —
    if extracted["honest"]:
        story.append(pdf_lib.page_break())
        story.append(pdf_lib.section_bar(
            "Честная оценка", anchor_slug="honest", outline_level=0,
        ))
        story.append(pdf_lib.spacer(4))
        render_md_body(story, extracted["honest"], styles)

    if extracted.get("general_comment"):
        story.append(pdf_lib.spacer(8))
        story.append(pdf_lib.labeled_para(
            "Общий комментарий:", extracted["general_comment"], styles["body"]))

    pdf_lib.build_doc(doc, story, with_background=True)
    return str(output_path)


def _render_variant(story, v: Variant, styles, *, slug: str, color: str,
                    has_comparison: bool) -> None:
    """Render один вариант: цветная плашка + интро (бюджет/ночи) + подсекции."""
    label = _variant_display(v.letter)
    bar_text = f"{label} — {v.title}" if v.title else label
    story.append(pdf_lib.section_bar(
        bar_text, anchor_slug=slug, outline_level=0, bg_color=color,
    ))
    story.append(pdf_lib.spacer(4))
    # Интро (бюджетный ⚠️-блок + распределение ночей).
    if v.intro:
        render_md_body(story, v.intro, styles)
    # Подсекции (Маршрут по дням / Что включает / ... / Кому подходит).
    for ss in v.subsections:
        story.append(pdf_lib.para(ss["heading"], styles["h3"], highlight_todo=False))
        render_md_body(story, ss["body"], styles)
    if v.user_comment:
        story.append(pdf_lib.labeled_para("Комментарий:", v.user_comment, styles["body"]))
    # Back-link на сводную таблицу.
    if has_comparison:
        story.append(pdf_lib.para("[↑ К сравнению](#comparison)", styles["small"],
                                  highlight_todo=False))
    story.append(pdf_lib.spacer(8))


# ---------------------------------------------------------------------------
# Renderer entry point + регистрация
# ---------------------------------------------------------------------------


def render_stage4(
    parsed: dict,
    *,
    recipient: str = "self",
    output_path: str | Path,
    **_kw: Any,
) -> "_renderer.RenderRequest":
    """Главный entry-point: распарсенный stage4 → PDF файл + RenderRequest."""
    extracted = extract_content(
        parsed, input_path=[_kw.get("source_file"), output_path])
    pdf_path = build_pdf(extracted, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage": "4_variants",
            "trip_id": parsed.get("trip_id"),
            "recipient": recipient,
            "variants_count": len(extracted["variants"]),
            "has_comparison": bool(extracted["comparison_rows"]),
        },
        metadata={
            "trip_id": parsed.get("trip_id"),
            "stage": parsed.get("stage"),
            "recipient": recipient,
            "font_family": pdf_lib._ACTIVE_FAMILY,
        },
        notes=[],
    )


# Регистрация — выполняется при импорте модуля.
_renderer.register_renderer("4_variants", "pdf", render_stage4)

"""stages/stage5.py — экстрактор контента + PDF builder для Stage 5.

**Контракт формата** артефакта (9 секций, блоки дней с иконками, `todo_verification_items`,
YAML) — канон `references/stage5/stage5-output-spec.md`; сверка —
`tests/test_format_contract.py`.

Stage 5 — финальный план поездки. PDF (self) рендерится в portrait A4
с continuous-flow дней и page break'ами на каждой большой секции
(Cover / Контекст / Шапка / Критические подготовительные пункты /
Маршрут по дням / Сводные таблицы / Гастрономия / План реагирования /
TODO).

Архитектура:
  1. `extract_content(parsed)` — превращает распарсенный stage5.md
     в структурированный dict (cover-данные, секции, день-блоки,
     таблицы, TODO-группы).
  2. `parse_day_block(section)` — разбивает body одного дня на
     emoji-markers (📍 🏨 🎯 💰 ⚠️).
  3. `build_pdf(extracted, output_path, recipient)` — собирает PDF
     через pdf_lib helpers.
  4. `render_stage5(parsed, recipient, output_path, **kw)` —
     entry-point, регистрируется в renderer._RENDERERS на import-time.

Stage-специфичные правила адаптации (например, что для recipient=parents
не показывать ⚠️-блоки в днях) — регистрируются через
`adapter.register_stage_extension`.
"""
from __future__ import annotations

import re
import dataclasses as dc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Импорт соседних модулей пакета — поддерживаем оба режима запуска
# (через `python -m export.stages.stage5` и как скрипт).
if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from export import adapter as _adapter   # type: ignore[no-redef]
    from export import pdf_lib                # type: ignore[no-redef]
    from export import renderer as _renderer  # type: ignore[no-redef]
    from export import cover_common            # type: ignore[no-redef]
    from export import travelers as _travelers  # type: ignore[no-redef]
else:
    from .. import adapter as _adapter
    from .. import pdf_lib
    from .. import renderer as _renderer
    from .. import cover_common
    from .. import travelers as _travelers


# ---------------------------------------------------------------------------
# Day-block parsing
# ---------------------------------------------------------------------------

# Иконки-маркеры в day-блоках Stage 5.
#
# Порядок важен: «⚠️» (U+26A0 U+FE0F) и «⚠» (U+26A0) — оба встречаются;
# регексп должен матчить оба. То же для пробельного варианта (U+200B и т.п.) —
# на всякий случай нормализуем перед поиском.
DAY_MARKERS: list[tuple[str, str]] = [
    ("📍", "Локация"),
    ("🏨", "Отель"),
    ("🎯", "Программа"),
    ("💰", "Бюджет"),
    ("⚠️", "Риски"),
    ("⚠",  "Риски"),
]

# Regex: матч начала строки на любой из маркеров. Используем lookahead
# чтобы split не съел сам маркер.
_MARKER_LINE_RE = re.compile(
    r"^(?P<marker>" + "|".join(re.escape(m) for m, _ in DAY_MARKERS) + r")\s*",
)


@dataclass
class DayMarker:
    """Один блок-маркер внутри дня (📍/🏨/🎯/💰/⚠️)."""
    icon: str
    label: str
    content: str          # текст ПОСЛЕ маркера, может быть многострочный
    is_bullets: bool = False  # содержит ли markdown bullet list


@dataclass
class DayBlock:
    """Распарсенный день."""
    day_num: int | None    # номер из заголовка, None если не распознан
    heading: str           # полный текст заголовка после `### `
    intro: str             # текст до первого маркера (обычно пусто)
    markers: list[DayMarker] = field(default_factory=list)
    region: str | None = None       # имя региона из маркера `[[регион: X]]`
    region_fields: dict = field(default_factory=dict)  # доп. поля маркера
                                    # (база/главное/буфер/бронь/риск/бюджет)
    booking: str | None = None      # статус брони из `[[бронь: план|забронировано]]`
    weather: list[str] = field(default_factory=list)  # риски из `[[погода: …]]`


# Маркер региона, который polish-шаг вставляет первой строкой тела дня:
# `[[регион: Сораксан]]` или с доп. полями для сводной таблицы:
# `[[регион: Сораксан | главное: Ульсанбави | бюджет: ~₩200 000]]`.
# Скрипт извлекает его, рендерит caption+полосу на плашке дня и собирает
# из этих полей сводную таблицу регионов + titler-блоки.
_REGION_MARKER_RE = re.compile(r"^\s*\[\[\s*регион:\s*(.+?)\s*\]\]\s*$", re.IGNORECASE | re.MULTILINE)

# Этап-2 статус-маркеры дня (опц., backward-compatible): встречаются ИНЛАЙН
# внутри контента маркеров (`🏨 [[бронь: план]] …`, `⚠️ … [[погода: …]]`),
# не отдельной строкой как регион. Извлекаются из всего тела дня и
# вырезаются, чтобы не протекать сырыми в PDF; рендерятся отдельными чипами.
_STATUS_MARKER_RE = re.compile(
    r"\[\[\s*(?P<key>бронь|погода)\s*:\s*(?P<val>.+?)\s*\]\]",
    re.IGNORECASE,
)


def _parse_region_marker(raw: str) -> tuple[str, dict]:
    """Разобрать содержимое маркера на (имя, поля).

    `raw` — текст между `[[регион:` и `]]`. Поля разделены `|`:
    `Сораксан | база: Сокчо | главное: Ульсанбави | буфер: день 5 | бюджет: ~₩200 000`.
    Первое поле — имя региона; остальные — пары `ключ: значение`.
    """
    parts = [p.strip() for p in raw.split("|")]
    name = parts[0].strip()
    fields: dict = {}
    for p in parts[1:]:
        if ":" in p:
            k, v = p.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    return name, fields


def parse_day_block(section: dict) -> DayBlock:
    """Распарсить одну H3-секцию `### День N ...` в DayBlock."""
    heading = section.get("heading", "")
    body = section.get("body", "") or ""
    day_num = _extract_day_num(heading)

    # Извлечь и убрать region-маркер из тела (если есть).
    region: str | None = None
    region_fields: dict = {}
    rm = _REGION_MARKER_RE.search(body)
    if rm:
        region, region_fields = _parse_region_marker(rm.group(1))
        body = _REGION_MARKER_RE.sub("", body, count=1).lstrip("\n")

    # Этап-2: извлечь и вырезать статус-маркеры брони/погоды (опц.). Бронь —
    # последнее значение (обычно одно); погода — список (может быть несколько).
    booking: str | None = None
    weather: list[str] = []
    for m in _STATUS_MARKER_RE.finditer(body):
        key = m.group("key").lower()
        val = m.group("val").strip()
        if key == "бронь":
            booking = val.lower()
        else:
            weather.append(val)
    if booking is not None or weather:
        # Вырезаем маркеры + подчищаем осиротевшие пробелы.
        body = _STATUS_MARKER_RE.sub("", body)
        body = re.sub(r"[ \t]{2,}", " ", body)

    lines = body.splitlines()
    intro_lines: list[str] = []
    markers: list[DayMarker] = []
    current_icon: str | None = None
    current_label: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_icon, current_label, current_lines
        if current_icon is not None:
            content = "\n".join(current_lines).strip()
            markers.append(DayMarker(
                icon=current_icon,
                label=current_label or "",
                content=content,
                is_bullets=_looks_like_bullets(content),
            ))
        current_icon = None
        current_label = None
        current_lines = []

    for line in lines:
        # Standalone разделитель-правило (`---`) — граница между днями в md,
        # не часть контента. Иначе он прилипает к последнему маркеру (⚠️) и
        # протекает сырым в PDF.
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        m = _MARKER_LINE_RE.match(line)
        if m:
            _flush()
            current_icon = m.group("marker")
            current_label = next(
                (lbl for ic, lbl in DAY_MARKERS if ic == current_icon),
                current_icon,
            )
            rest = line[m.end():]
            if rest.strip():
                current_lines.append(rest)
            continue
        # Не-маркерная строка: продолжение текущего блока или intro.
        if current_icon is None:
            intro_lines.append(line)
        else:
            current_lines.append(line)
    _flush()

    return DayBlock(
        day_num=day_num,
        heading=heading,
        intro="\n".join(intro_lines).strip(),
        markers=markers,
        region=region,
        region_fields=region_fields,
        booking=booking,
        weather=weather,
    )


def _extract_day_num(heading: str) -> int | None:
    """Достать число из заголовка `День N ...`."""
    m = re.search(r"День\s+(\d+)", heading)
    return int(m.group(1)) if m else None


def _looks_like_bullets(text: str) -> bool:
    """Содержит ли текст хотя бы одну строку, начинающуюся с `- `?"""
    return any(line.lstrip().startswith("- ") for line in text.splitlines())


def split_bullets_and_intro(content: str) -> tuple[str, list[str]]:
    """Из текста маркера выделить intro-часть и bullet-список.

    Типовой паттерн в Stage 5:
        **Программа:**
        - первый пункт
        - второй пункт
    Возвращаем `("**Программа:**", ["первый пункт", "второй пункт"])`.

    Если bullets нет — `(content, [])`.
    """
    lines = content.splitlines()
    intro: list[str] = []
    bullets: list[str] = []
    current_bullet: list[str] = []
    in_list = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- "):
            if current_bullet:
                bullets.append(" ".join(s.strip() for s in current_bullet))
                current_bullet = []
            current_bullet.append(stripped[2:])
            in_list = True
        elif in_list and (line.startswith("  ") or line.startswith("\t")):
            # Продолжение последнего bullet'а.
            current_bullet.append(line.strip())
        else:
            if current_bullet:
                bullets.append(" ".join(s.strip() for s in current_bullet))
                current_bullet = []
            if in_list and not line.strip():
                # Пустая строка после bullets — заканчиваем список.
                continue
            intro.append(line)
            in_list = False
    if current_bullet:
        bullets.append(" ".join(s.strip() for s in current_bullet))
    return "\n".join(intro).strip(), bullets


# ---------------------------------------------------------------------------
# Markdown table extraction
# ---------------------------------------------------------------------------

_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$")


def extract_tables_and_text(body: str) -> list[dict]:
    """Распарсить body секции на чередующиеся блоки таблиц и текста.

    Возвращает список dict'ов:
      - `{"type": "table", "rows": [[cell, cell, ...], ...]}` — header в [0]
      - `{"type": "text", "content": "..."}` — markdown-фрагмент текста

    Используется для секций «Сводные таблицы», «План реагирования на риски»
    и т.п., где таблицы перемежаются с пояснительным текстом.
    """
    lines = body.splitlines()
    blocks: list[dict] = []
    i = 0
    text_buf: list[str] = []

    def _flush_text() -> None:
        nonlocal text_buf
        text = "\n".join(text_buf).strip()
        if text:
            blocks.append({"type": "text", "content": text})
        text_buf = []

    while i < len(lines):
        line = lines[i]
        # Таблица: текущая строка содержит `|`, следующая — разделитель.
        if "|" in line and i + 1 < len(lines) and _TABLE_DELIM_RE.match(lines[i + 1]):
            _flush_text()
            header = _split_md_row(line)
            i += 2  # пропустили заголовок и разделитель
            rows = [header]
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_md_row(lines[i]))
                i += 1
            # Нормализуем длину рядов под header.
            ncols = len(header)
            normalized = [r + [""] * (ncols - len(r)) for r in rows]
            blocks.append({"type": "table", "rows": normalized})
            continue
        text_buf.append(line)
        i += 1
    _flush_text()
    return blocks


def _split_md_row(line: str) -> list[str]:
    """Разбить ряд markdown-таблицы на ячейки."""
    parts = line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


# ---------------------------------------------------------------------------
# Главный экстрактор
# ---------------------------------------------------------------------------

# Канонические заголовки H2-секций Stage 5. Если порядок/имена изменятся
# (schema evolution) — добавлять сюда; неузнанные секции рендерятся
# generic-способом в конце документа.
KNOWN_H2 = {
    "Контекст и ключевые параметры",
    "Шапка",
    "Критические подготовительные пункты",
    "Маршрут по дням",
    "Сводные таблицы",
    "План реагирования на риски",
    "Чеклист за 2 недели до поездки",
    "TODO для верификации",
}


def _heading_slug(heading: str, idx: int) -> str:
    """ASCII-safe slug для anchor-имени.

    Reportlab/PDF принимают любые Unicode в `<a name="..."/>`, но безопаснее
    использовать ASCII. Используем порядковый индекс — opaque, гарантированно
    уникальный, не ломается на переименовании секции.
    """
    return f"sect-{idx}"


def build_anchor_map(extracted: dict) -> dict[str, str]:
    """Собрать карту heading → slug для всех H2-секций в документе.

    Используется для inline-ссылок `## Heading` внутри body.
    """
    anchors: dict[str, str] = {}
    idx = 0
    # Канонические секции — в порядке появления.
    canonical_order = [
        ("context", "Контекст и ключевые параметры"),
        ("header", "Шапка"),
        ("critical_prep", "Критические подготовительные пункты"),
        ("days", "Маршрут по дням"),
        ("summary", "Сводные таблицы"),
        ("risk_plan_blocks", "План реагирования на риски"),
        ("checklist_2w", "Чеклист за 2 недели до поездки"),
        ("todo", "TODO для верификации"),
    ]
    for key, heading in canonical_order:
        if extracted.get(key):
            idx += 1
            anchors[heading] = _heading_slug(heading, idx)
    # Под-секции «Сводных таблиц» — короткий ключ (Бюджет/Транспорт/Гастрономия)
    # → summary-{si}. Нужно, чтобы инлайн-ссылка «## Сводные таблицы → Бюджет»
    # линковала и слово «Бюджет» на таблицу бюджета (slug совпадает с тем, что
    # ставит render-loop в build_pdf).
    for si, item in enumerate(extracted.get("summary") or [], start=1):
        short = item["title"].split("(")[0].strip()
        if short and short not in anchors:
            anchors[short] = f"summary-{si}"
    # Незнакомые H2-секции (schema evolution).
    for ex in extracted.get("extra") or []:
        idx += 1
        anchors[ex["heading"]] = _heading_slug(ex["heading"], idx)
    return anchors


def extract_content(parsed: dict, *, input_path: "Path | None" = None) -> dict:
    """Извлечь структуру для PDF-builder'а из распарсенного stage5.md.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10).

    Возвращает dict с ключами:
      - `cover`: {trip_id, duration_nights, chosen_variant, mode, ...}
      - `title`: первый H1 (для cover-страницы)
      - `context`: body «Контекст и ключевые параметры»
      - `header`: body «Шапка»
      - `critical_prep`: [{title, body}] для H3 под «Критические…»
      - `route_intro`: текст до первого `### День`
      - `days`: list[DayBlock]
      - `summary`: [{title, body, blocks}] для H3 под «Сводные таблицы»
      - `risk_plan_blocks`: parsed blocks (text+table)
      - `checklist_2w`: body «Чеклист за 2 недели до поездки» (или None)
      - `todo`: [{title, items}] для H3 под «TODO для верификации»
      - `extra`: list of (heading, body) для незнакомых H2
      - `frontmatter`: dict — для cover-meta
      - `frontmatter_warnings`: list[str] — для diagnostic block
    """
    sections = parsed.get("sections") or []
    fm = parsed.get("frontmatter") or {}
    fm_warn = list(fm.get("warnings") or [])

    out: dict[str, Any] = {
        "title": parsed.get("title"),
        "frontmatter": fm,
        "frontmatter_warnings": fm_warn,
        "cover": _build_cover(parsed, input_path=input_path),
        "context": None,
        "header": None,
        "critical_prep": [],
        "route_intro": "",
        "days": [],
        "summary": [],
        "risk_plan_blocks": [],
        "checklist_2w": None,
        "todo": [],
        "extra": [],
    }

    for sec in sections:
        h = sec["heading"]
        if h == "Контекст и ключевые параметры":
            out["context"] = sec["body"]
        elif h == "Шапка":
            out["header"] = sec["body"]
        elif h == "Критические подготовительные пункты":
            out["critical_prep"] = [
                {"title": ss["heading"], "body": ss["body"]}
                for ss in sec.get("subsections", [])
            ]
        elif h == "Маршрут по дням":
            out["route_intro"] = sec["body"]
            out["days"] = [
                parse_day_block(ss) for ss in sec.get("subsections", [])
                if ss["heading"].startswith("День")
            ]
        elif h == "Сводные таблицы":
            for ss in sec.get("subsections", []):
                out["summary"].append({
                    "title": ss["heading"],
                    "blocks": extract_tables_and_text(ss["body"]),
                })
        elif h == "План реагирования на риски":
            out["risk_plan_blocks"] = extract_tables_and_text(sec["body"])
        elif h == "Чеклист за 2 недели до поездки":
            out["checklist_2w"] = sec["body"]
        elif h == "TODO для верификации":
            out["todo"] = [
                {"title": ss["heading"], "body": ss["body"]}
                for ss in sec.get("subsections", [])
            ]
            # Если у TODO нет H3-подгрупп — складываем body как одну группу.
            if not out["todo"] and sec["body"].strip():
                out["todo"] = [{"title": "TODO", "body": sec["body"]}]
        else:
            out["extra"].append({"heading": h, "body": sec["body"],
                                 "subsections": sec.get("subsections", [])})

    return out


def _build_cover(parsed: dict, *, input_path: "Path | None" = None) -> dict:
    """Собрать данные для cover-страницы из frontmatter.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10)."""
    fm = parsed.get("frontmatter") or {}
    return {
        "trip_id": fm.get("trip_id") or "",
        "duration_nights": fm.get("duration_nights"),
        "chosen_variant": fm.get("chosen_variant"),
        "chosen_variant_raw": fm.get("chosen_variant_raw"),
        "mode": fm.get("mode"),
        "budget_status": fm.get("budget_status"),
        "total_budget_rub": fm.get("total_budget_rub"),
        "budget_target_rub": fm.get("budget_target_rub"),
        "home_eq_start": fm.get("home_eq_start"),
        "todo_items_count": fm.get("todo_verification_items"),
        "created": fm.get("created"),
        "travelers_profile": fm.get("travelers_profile"),
        "who_goes": _travelers.resolve_travelers(fm, {}, input_path),
        "retrospective": fm.get("retrospective"),
    }


def _human_cover_title(cover: dict) -> str:
    """Человеческий заголовок обложки из trip_id (без pipeline-жаргона).

    «корея_2024-03» → «Корея»; «камбоджа_лаос_2026-02» → «Камбоджа · Лаос»;
    группа-токены («китай_родители_…» → «Китай») в гео-заголовок не идут.
    """
    trip = cover.get("trip_id") or ""
    base = re.sub(r"_\d{4}-\d{2}.*$", "", trip)
    names = [p.capitalize() for p in base.split("_")
             if p and not cover_common.is_non_geo_token(p)]
    return " · ".join(names) if names else "Финальный план поездки"


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------


# Display-переименования H2: внутренний ключ (для анкоров/outline) остаётся
# прежним, на плашке рисуется понятное имя. «Шапка» — pipeline-жаргон,
# никто не понимает; контент — паспорт/визы/перелёт/валюта.
_H2_DISPLAY_RENAME = {
    "Шапка": "Документы, визы, перелёт",
}

# ── Что НЕ едет в дорожный документ (Stage 6) ───────────────────────────────
# Stage 6 — то, что печатают и открывают с телефона В ПОЕЗДКЕ. Планировочные
# разделы там мешают: «Чего нет в маршруте и почему» объясняет уже принятые
# решения, «Чеклист за 2 недели до поездки» к моменту выезда отработан, «TODO
# для верификации» и «Обоснование ключевых решений» — рабочая кухня, «Diff с
# предыдущим планом» — история версий.
#
# Отбор ЗАПРЕТИТЕЛЬНЫЙ, и это принципиально. Разрешительный («оставить только
# нужное») терял бы две вещи: содержимое, случайно попавшее под другой
# заголовок, и текст между секциями. Здесь же новая, ещё не известная коду
# секция доедет до документа, а не исчезнет молча: унести лишнюю страницу
# дешевле, чем недосчитаться нужной в дороге.
#
# Ветки различаются ОСОЗНАННО, и по содержанию различие ровно одно — прогресс
# подготовки:
#   • «TODO для верификации» и «Чеклист за 2 недели» в HTML ОСТАЮТСЯ: страница
#     интерактивна, отметки пишутся обратно в 5_vX, и в поездке по ним видно,
#     что сделано, а что пропущено;
#   • в PDF их нет: печатный лист отметок не принимает, и они там мёртвый груз.
# Всё остальное режется одинаково — иначе PDF и HTML стали бы разными
# документами под одним именем.
#
# TRIP_DROP_PRINT — не про содержание, а про печатную оснастку: видимое
# оглавление со ссылками существует только в PDF-ветке (в HTML его нет вовсе,
# там навигация — интерактивный слой). В дорожном документе оно занимает
# половину обложки, дублирует PDF-outline (закладки сайдбара остаются) и
# бесполезно на бумаге, где листают, а не кликают. Поэтому набор попадает
# только в PDF и НЕ создаёт расхождения между доставляемыми документами.
# ⚠ SYNC: наборы ниже — единственный источник правды для обеих веток; состав и
# асимметрия сверяются тестом.
TRIP_DROP_CORE = ("excluded", "logic")           # чистая планировочная кухня
TRIP_DROP_PROGRESS = ("todo", "checklist_2w", "todo_marks")   # прогресс подготовки
TRIP_DROP_PRINT = ("toc", "hard_breaks")         # печатная оснастка
# Кабинетные атрибуты: следы того, что документ когда-то был предметом выбора и
# защиты бюджета. В поездке варианта уже нет, вердикт «уложились в бюджет»
# вынесен, вероятность сценария либо реализовалась, либо нет, а ссылки на стадии
# конвейера читателю плана вообще ничего не значат. Режется в ОБЕИХ ветках —
# это не про носитель, а про роль документа.
TRIP_DROP_OFFICE = ("variant", "budget_note", "risk_probability", "pipeline_refs")
TRIP_DROP_HTML = TRIP_DROP_CORE + TRIP_DROP_OFFICE   # HTML: прогресс сохраняем
TRIP_DROP_PDF = (TRIP_DROP_CORE + TRIP_DROP_OFFICE
                 + TRIP_DROP_PROGRESS + TRIP_DROP_PRINT)

# ── Текстовые фильтры дорожного документа ──────────────────────────────────
# Ссылка на стадию конвейера («Stage 3 #43», «vs target Stage 4») — служебная
# адресация внутри пайплайна. В плане, который читают в дороге, это шум: номера
# стадий там не с чем соотнести.
_PIPE_REF = r"Stage[ \t]*\d+(?:[ \t]*[/,][ \t]*\d+)?(?:[ \t]*#\d+)?"
# Скобка целиком из ссылки — уносится вместе со скобкой: «фотографу (Stage 3
# #43), 5 мин» → «фотографу, 5 мин».
_PIPE_PAREN_ONLY_RE = re.compile(rf"[ \t]*\((?:см\.[ \t]*)?{_PIPE_REF}\)")
# Ссылка в начале скобки — уносится вместе со своей запятой, иначе остаётся
# «(, без изменений)».
_PIPE_PAREN_LEAD_RE = re.compile(rf"\((?:см\.[ \t]*)?{_PIPE_REF},[ \t]*")
# «источник из Stage 0: …» → «источник: …» (без этого правила остаётся «из »).
_PIPE_OF_RE = re.compile(rf"[ \t]*\bиз[ \t]+{_PIPE_REF}")
_PIPE_BARE_RE = re.compile(rf"[ \t]*\b{_PIPE_REF}")

# Метка TODO внутри операционного текста. Квалификатор — только словесный
# («за 2 недели»): скобки, слэши и `[` из него исключены, иначе выражение
# уезжает в markdown-ссылку и съедает URL до двоеточия в «https:».
_TODO_QUAL = r"[А-Яа-яЁёA-Za-z0-9 \t\-]{1,25}"
_TODO_MARK_RE = re.compile(
    r"\*{0,2}\bTODO\b\*{0,2}"
    r"(?:"
    rf"[ \t]*\*{{0,2}}(?:\({_TODO_QUAL}\)|{_TODO_QUAL})?\*{{0,2}}[ \t]*[:：]\*{{0,2}}"
    r"|(?=[ \t]+[А-Яа-яЁёA-Za-z])"
    r")"
    r"[ \t]*(\S)?"
)


# Скобочная форма маркера — «условия полиса сверить (TODO).». Голое слово в
# скобках вместе со своей скобкой: это пометка, а не упоминание.
_TODO_PAREN_RE = re.compile(r"[ \t]*\(TODO\)")


def _strip_todo_mark(m: "re.Match[str]") -> str:
    """Снять метку, подняв следующее слово в верхний регистр, если метка стояла
    в начале предложения («Багаж включён. TODO: онлайн-регистрация» →
    «Багаж включён. Онлайн-регистрация»)."""
    nxt = m.group(1) or ""
    head = m.string[:m.start()].rstrip()
    if nxt and (not head or head[-1] in ".!?…"):
        nxt = nxt.upper()
    return nxt


def scrub_text_for_trip(text: str, drop: tuple[str, ...]) -> str:
    """Текстовые фильтры дорожного документа поверх одной строки.

    Снимается ТОЛЬКО разметка-адресация, содержание остаётся: у ссылки на стадию
    уносится сама ссылка, у TODO — метка, но не задача. Бесколоночный «TODO» в
    прозе («удалён из дня 10 и из TODO», «Было (v5, TODO)») не трогается — это
    упоминание, а не маркер."""
    if "pipeline_refs" in drop:
        text = _PIPE_PAREN_ONLY_RE.sub("", text)
        text = _PIPE_PAREN_LEAD_RE.sub("(", text)
        text = _PIPE_OF_RE.sub("", text)
        text = _PIPE_BARE_RE.sub("", text)
    if "todo_marks" in drop:
        text = _TODO_PAREN_RE.sub("", text)
        text = _TODO_MARK_RE.sub(_strip_todo_mark, text)
    return text


def apply_trip_text_filters(extracted: dict, drop: tuple[str, ...]) -> dict:
    """Прогнать текстовые фильтры по всему разобранному артефакту.

    Обход общий, а не по списку полей: текст Stage 5 живёт в днях, таблицах,
    блоках, сводках и незнакомых H2 — перечислять их значило бы забыть один и
    получить документ, вычищенный наполовину. Выражения привязаны к «Stage»+цифра
    и к маркеру TODO, поэтому глобальный проход по строкам безопасен."""
    if not ({"pipeline_refs", "todo_marks"} & set(drop)):
        return extracted

    def walk(o):
        if isinstance(o, str):
            return scrub_text_for_trip(o, drop)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        # Дни и маркеры — dataclass'ы (DayBlock/DayMarker), а не dict: без этой
        # ветки обход тихо проходил мимо всего тела маршрута, то есть мимо
        # большей части документа.
        if dc.is_dataclass(o) and not isinstance(o, type):
            return dc.replace(o, **{f.name: walk(getattr(o, f.name))
                                    for f in dc.fields(o)})
        if isinstance(o, tuple):
            return type(o)(*(walk(x) for x in o)) if hasattr(o, "_fields") \
                else tuple(walk(x) for x in o)
        return o

    return walk(extracted)


# Колонка вероятности в плане реагирования на риски: кабинетная величина. В
# поездке сценарий либо наступил, либо нет — нужно «что делать», а не «~15–20%».
_RISK_PROB_HEAD_RE = re.compile(r"вероятн", re.I)


def drop_risk_probability(blocks: list[dict] | None) -> list[dict]:
    """Убрать из таблиц колонку «Вероятность» (по заголовку, а не по индексу —
    порядок колонок в 5_vX не гарантирован). Таблицы без такой колонки и
    текстовые блоки проходят насквозь."""
    out: list[dict] = []
    for b in (blocks or []):
        rows = b.get("rows") if b.get("type") == "table" else None
        if not rows or not rows[0]:
            out.append(b)
            continue
        idx = [i for i, h in enumerate(rows[0]) if _RISK_PROB_HEAD_RE.search(str(h))]
        if not idx or len(rows[0]) - len(idx) < 2:
            # Убирать нечего — либо колонки нет, либо от таблицы остался бы
            # один столбец: тогда лучше оставить как есть.
            out.append(b)
            continue
        keep = [i for i in range(len(rows[0])) if i not in idx]
        out.append({**b, "rows": [[r[i] for i in keep if i < len(r)] for r in rows]})
    return out

TRIP_DROP_HEADINGS = ("diff с предыдущим планом",)


def drop_extra_for_trip(extra: list | None) -> list:
    """Незнакомые H2 для дорожного документа: режем ТОЛЬКО по точному имени из
    `TRIP_DROP_HEADINGS`, всё остальное проходит насквозь."""
    return [e for e in (extra or [])
            if (e.get("heading") or "").strip().lower() not in TRIP_DROP_HEADINGS]


def _h2(story, heading: str, anchors: dict[str, str], styles,
        *, in_outline: bool = True) -> None:
    """H2-заголовок как залитая плашка-секция + anchor + PDF-outline.

    На плашке — display-имя (`_H2_DISPLAY_RENAME`), но anchor-slug и
    outline-title привязаны к исходному heading (стабильность ссылок).
    `in_outline=False` — плашка с destination, но БЕЗ записи в PDF-outline
    (например, «Сводные таблицы»: в outline идут её подсекции).
    """
    slug = anchors.get(heading)
    display = _H2_DISPLAY_RENAME.get(heading, heading)
    story.append(pdf_lib.spacer(4))
    story.append(pdf_lib.section_bar(
        display,
        anchor_slug=slug,
        outline_level=0 if (slug and in_outline) else None,
    ))
    story.append(pdf_lib.spacer(4))


# Порог условного разрыва после TOC (P1.5): записей больше — разрыв страницы
# допустим (длинное оглавление + контент на одной странице теснит); ≤ порога —
# контент течёт сразу (не плодим пустую страницу под коротким TOC). Это
# типографская норма (экономия пустот), не эмпирический порог из исследований.
_TOC_BREAK_THRESHOLD = 10

# Сколько места должно остаться на листе, чтобы секция начиналась здесь, а не с
# новой страницы (пункты; полезная высота A4 при полях 1.3 см ≈ 768 pt). Четверть
# листа — столько нужно, чтобы после заголовка поместилось несколько строк:
# заголовок-сирота у нижнего края читается хуже, чем перенос. Порог применяется
# только в дорожном документе («hard_breaks» в drop) — планировочный Stage 5
# сохраняет разбивку «одна секция = свои страницы».
_SECTION_MIN_SPACE_PT = 190


def _build_toc(entries: list[tuple[str, str]], styles) -> list:
    """Видимое оглавление из (заголовок, slug) с кликабельными ссылками.

    Возвращает список flowables: заголовок «Содержание» + строка-ссылка
    `[Заголовок](#slug)` на каждую секцию + условный разрыв/спейсер в конце.
    Пустой `entries` → пустой список (оглавление не рисуется).
    """
    if not entries:
        return []
    flows: list = [
        pdf_lib.para("Содержание", styles["h3"], highlight_todo=False),
        pdf_lib.spacer(2),
    ]
    for title, slug in entries:
        flows.append(pdf_lib.para(
            f"[{title}](#{slug})", styles["body"], highlight_todo=False,
        ))
    flows.append(
        pdf_lib.page_break() if len(entries) > _TOC_BREAK_THRESHOLD
        else pdf_lib.spacer(8)
    )
    return flows


def _collapse_double_breaks(story: list) -> list:
    """Убрать подряд идущие PageBreak'и (пустые страницы), сохранив контент.

    Возникает, когда длинный TOC заканчивается разрывом, а следом идёт
    leading-разрыв инжекта карты Stage 6 → два разрыва подряд = пустая страница.
    """
    if not pdf_lib.REPORTLAB_AVAILABLE:
        return story
    out: list = []
    prev_break = False
    for f in story:
        is_break = isinstance(f, pdf_lib.PageBreak)
        if is_break and prev_break:
            continue
        out.append(f)
        prev_break = is_break
    return out


def build_pdf(extracted: dict, output_path: str | Path, *, recipient: str = "self",
              inject: dict | None = None,
              drop: tuple[str, ...] = ()) -> str:
    """Собрать PDF Stage 5 из извлечённой структуры.

    `inject` — опциональный пакет добавок для механического ассемблера Stage 6
    (см. `stages/stage6.py`). При `None` (дефолт Stage 5) поведение неизменно.
    Поддерживаемые ключи:
      - `map_flowables` / `map_toc` — обзорная карта после обложки/TOC;
      - `appendix_flowables` / `appendix_toc` — досье/бронь/углубления перед
        приложением «Обоснование»;
      - `footer` — переопределить текст футера (дата создания 6_final);
      - `title` — переопределить заголовок PDF-документа.
    """
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 5 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    inject = inject or {}
    # Текстовые фильтры дорожного документа — до рендера и один раз на весь
    # артефакт: дальше `extracted` читают три десятка мест, и точечная чистка
    # означала бы вычищенный наполовину документ. При пустом `drop` (обычный
    # Stage 5) возвращается тот же объект без копирования.
    extracted = apply_trip_text_filters(extracted, drop)
    # Разрыв перед секцией: жёсткий (планировочный Stage 5) или условный
    # (дорожный документ). Условный не плодит листов с тремя строками — а их
    # набиралось на четверть документа, потому что каждая секция стартовала
    # с новой страницы независимо от своей длины.
    _soft_breaks = "hard_breaks" in drop

    def _sect_break():
        return (pdf_lib.cond_page_break(_SECTION_MIN_SPACE_PT) if _soft_breaks
                else pdf_lib.page_break())

    styles = pdf_lib.get_styles()
    doc = pdf_lib.make_doc(
        output_path,
        orientation="portrait",
        title=inject.get("title")
        or f"Финальный план — {extracted['cover'].get('trip_id', '')}",
        subject=inject.get("subject") or "",
    )
    if inject.get("footer") is not None:
        pdf_lib.set_footer_text(inject["footer"])
    else:
        _created = extracted["cover"].get("created") or ""
        pdf_lib.set_footer_text(f"создан {_created}".strip() if _created else "")
    # Регистрируем anchor-карту, чтобы inline `## Heading` стало кликабельным.
    anchors = build_anchor_map(extracted)
    pdf_lib.set_section_anchors(anchors)
    # Карта регион→цвет по порядку появления (если polish проставил регионы).
    region_colors = _build_region_color_map(extracted["days"])
    # Группировка дней по регионам (для сводной таблицы + titler-блоков).
    region_groups = group_regions(extracted["days"])
    # day_num → (idx, total, group) для первого дня каждого региона — titler.
    titler_at: dict[int, tuple[int, int, RegionGroup]] = {}
    for gi, g in enumerate(region_groups, start=1):
        first = g.days[0]
        if first.day_num:
            titler_at[first.day_num] = (gi, len(region_groups), g)
    try:
        story: list[Any] = []
        # Destination `doc-top` (цель ссылки «В начало» из TOC + outline-запись)
        # ставит заголовок обложки в `_build_cover_page` — отдельный anchor не нужен.

        # — Cover page —
        #   Тезис «Замысел маршрута» (#14): извлекаем и работаем с КОПИЕЙ тела
        #   контекста без строки тезиса (иначе продублируется у фронта). Сам
        #   `extracted["context"]` НЕ мутируем (build_pdf идемпотентен).
        #   Backward-compat: тезис отсутствует → обложка как раньше.
        context_body = extracted.get("context") or ""
        thesis = _extract_thesis(context_body)
        if thesis:
            context_body = _strip_thesis_line(context_body)
        route = _build_route_string(region_groups)
        tempo = _extract_tempo(context_body)
        # Hero-данные обложки: лента маршрута (базы + ночи) + статбенд.
        ribbon_stops = [(g.name, f"{len(g.days)} н") for g in region_groups]
        _day_dates = [d for d in (_day_date(x) for x in extracted["days"]) if d]
        _cv = extracted["cover"]
        stat_rows: list[tuple[str, str, str]] = []
        if _cv.get("duration_nights"):
            stat_rows.append(("Длительность", str(_cv["duration_nights"]), "ночей"))
        if _day_dates:
            stat_rows.append(("Даты", f"{_day_dates[0]}–{_day_dates[-1]}", ""))
        if region_groups:
            stat_rows.append(("Базы", str(len(region_groups)), "городов"))
        if _cv.get("budget_target_rub"):
            stat_rows.append(
                ("Бюджет всё включено", f"₽{round(_cv['budget_target_rub'] / 1000)}К", ""))
        _build_cover_page(story, extracted["cover"], extracted.get("title"), styles,
                          route=route, tempo=tempo, thesis=thesis,
                          ribbon_stops=ribbon_stops, stat_rows=stat_rows,
                          show_todo_count="todo" not in drop,
                          show_variant="variant" not in drop,
                          show_budget_note="budget_note" not in drop)

        # — TOC (P1.5): записи собираются во время рендера секций ниже;
        #   готовый блок вставляется между обложкой и контентом (индекс
        #   cover_end). Условный разрыв после TOC — внутри _build_toc. —
        cover_end = len(story)
        toc_entries: list[tuple[str, str]] = []

        # — Обзорная карта маршрута (Stage 6 inject) — встраивается СРАЗУ после
        #   обложки; TOC, вставляемый ниже на cover_end, окажется перед ней →
        #   итог: обложка → TOC → карта → контент (§7.1 порядок). —
        if inject.get("map_flowables"):
            story.extend(inject["map_flowables"])
            toc_entries.extend(inject.get("map_toc") or [])

        def _emit_h2(heading: str, *, in_outline: bool = True) -> None:
            """H2-плашка + запись в TOC (если у секции есть anchor-slug)."""
            _h2(story, heading, anchors, styles, in_outline=in_outline)
            slug = anchors.get(heading)
            if slug:
                toc_entries.append((_H2_DISPLAY_RENAME.get(heading, heading), slug))

        # — Контекст разнесён (P1.2): «Чего нет» — у фронта (здесь, под
        #   cover-таблицей), «Логика ключевых решений» — в приложение в конце.
        #   Парсим один раз; logic_blocks используются в конце build_pdf. —
        context_parts = _parse_context_parts(context_body)
        if context_body:
            story.append(pdf_lib.spacer(10))
            _render_excluded_front(story, context_parts, styles,
                                   drop_excluded="excluded" in drop)

        # — Сводная таблица регионов — с НОВОЙ страницы, со ссылками на дни.
        #   Anchor `regions-summary` — для back-link'ов «↑ К сводной» из дней. —
        if region_groups:
            story.append(_sect_break())
            story.append(pdf_lib.heading_paragraph(
                "Регионы маршрута", styles["h2"],
                anchor_slug="regions-summary", outline_level=0,
            ))
            toc_entries.append(("Регионы маршрута", "regions-summary"))
            _build_region_summary(story, region_groups, styles)

        # — Шапка —
        if extracted["header"]:
            story.append(_sect_break())
            _emit_h2("Шапка")
            _render_markdown_body(story, extracted["header"], styles)

        # — Критические подготовительные пункты —
        if extracted["critical_prep"]:
            story.append(_sect_break())
            _emit_h2("Критические подготовительные пункты")
            for prep in extracted["critical_prep"]:
                story.append(pdf_lib.para(prep["title"], styles["h3"]))
                _render_markdown_body(story, prep["body"], styles)

        # — Маршрут по дням —
        if extracted["days"]:
            story.append(_sect_break())
            _emit_h2("Маршрут по дням")
            if extracted["route_intro"]:
                _render_markdown_body(story, extracted["route_intro"], styles)
            for day in extracted["days"]:
                # Перед первым днём региона — titler-блок (РЕГИОН N ИЗ M).
                if day.day_num in titler_at:
                    gi, total, g = titler_at[day.day_num]
                    dates_list = [x for x in (_day_date(d) for d in g.days) if x]
                    dates = (f"{dates_list[0]}–{dates_list[-1]}"
                             if len(dates_list) > 1 else (dates_list[0] if dates_list else ""))
                    nums = [d.day_num for d in g.days if d.day_num]
                    day_range = (f"дни {nums[0]}–{nums[-1]}"
                                 if len(nums) > 1 else f"день {nums[0]}")
                    meta = f"{day_range} · {dates} · {len(g.days)} ноч."
                    base = g.fields.get("база")
                    if base:
                        meta += f" · {base}"
                    bullets = _region_titler_bullets(g.fields)
                    intro = g.fields.get("описание")
                    story.append(pdf_lib.spacer(6))
                    story.append(pdf_lib.region_titler(
                        gi, total, g.name, meta,
                        region_colors.get(g.name, pdf_lib.COLORS["primary"]),
                        bullets=bullets,
                        intro=intro,
                        anchor_slug=f"region-{gi}",
                    ))
                    story.append(pdf_lib.spacer(4))
                _render_day(story, day, styles, recipient=recipient,
                            region_colors=region_colors,
                            has_region_summary=bool(region_groups))

        # — Сводные таблицы — сама секция НЕ в outline; в outline идут её
        #   подсекции (Транспорт / Бюджет / Гастрономия) как отдельные пункты.
        if extracted["summary"]:
            story.append(_sect_break())
            _emit_h2("Сводные таблицы", in_outline=False)
            for si, item in enumerate(extracted["summary"], start=1):
                story.append(pdf_lib.heading_paragraph(
                    item["title"], styles["h3"],
                    anchor_slug=f"summary-{si}", outline_level=0,
                ))
                _render_blocks(story, item["blocks"], styles)
                # Бюджет — единый авторитетный источник (P2.3): пометка под
                # таблицей, что дневные суммы производны. TODO-маркеры в
                # самих ячейках подсвечивает data_table (см. md_inline_to_rl).
                if _is_budget_title(item["title"]):
                    story.append(pdf_lib.spacer(2))
                    story.append(pdf_lib.para(
                        "Эта таблица — единственный авторитетный источник по бюджету; "
                        "суммы в дневных блоках производны и могут не сходиться. "
                        "Любая непроверенная цифра помечена TODO.",
                        styles["small"], highlight_todo=False,
                    ))

        # — План реагирования на риски (self only) —
        if extracted["risk_plan_blocks"] and recipient == "self":
            story.append(_sect_break())
            _emit_h2("План реагирования на риски")
            _drop_prob = "risk_probability" in drop
            _render_blocks(story,
                           drop_risk_probability(extracted["risk_plan_blocks"])
                           if _drop_prob else extracted["risk_plan_blocks"],
                           styles)
            # Провенанс вероятностей (P2.5): одной строкой-сноской под таблицей —
            # не колонкой, не в строках (структура таблицы неприкосновенна).
            # Без самой колонки сноска объясняет то, чего в документе нет.
            if not _drop_prob:
                story.append(pdf_lib.spacer(2))
                story.append(pdf_lib.para(
                    "Вероятности — экспертная калибровка по сезонной климатологии и "
                    "практике маршрута, не точные статистические данные.",
                    styles["small"], highlight_todo=False,
                ))

        # — TODO для верификации (self only) —
        if extracted["todo"] and recipient == "self" and "todo" not in drop:
            story.append(_sect_break())
            _emit_h2("TODO для верификации")
            for grp in extracted["todo"]:
                story.append(pdf_lib.para(grp["title"], styles["h3"]))
                _render_markdown_body(story, grp["body"], styles)

        # — Чеклист за 2 недели — ПОСЛЕ TODO (фидбэк): сначала список проверок,
        #   потом предвыездная подготовка, затем приложение-обоснование. —
        if extracted["checklist_2w"] and "checklist_2w" not in drop:
            story.append(_sect_break())
            _emit_h2("Чеклист за 2 недели до поездки")
            _render_markdown_body(story, extracted["checklist_2w"], styles)

        # — Stage 6 inject: Дорожное досье / Бронирования / Углубления —
        #   полноценные приложения после чеклиста, перед «Обоснованием». Контент
        #   собран в stage6.py из 6_final.md (механический ассемблер). —
        if inject.get("appendix_flowables"):
            story.extend(inject["appendix_flowables"])
            toc_entries.extend(inject.get("appendix_toc") or [])

        # — Приложение: Обоснование ключевых решений (P1.2, review-слой) —
        #   Глубокий рационал «Логики» — в конце, перед Diff. Только self:
        #   полевая версия (field) и parents этот слой не получают.
        if (context_parts.get("logic_blocks") and recipient == "self"
                and "logic" not in drop):
            story.append(_sect_break())
            story.append(pdf_lib.heading_paragraph(
                "Обоснование ключевых решений", styles["h2"],
                anchor_slug="decision-logic", outline_level=0,
            ))
            toc_entries.append(("Обоснование ключевых решений", "decision-logic"))
            story.append(pdf_lib.spacer(4))
            _render_decision_logic(story, context_parts, styles)

        # — Любые незнакомые H2-секции (schema evolution) —
        for ex in (drop_extra_for_trip(extracted["extra"]) if drop
                   else extracted["extra"]):
            story.append(_sect_break())
            _emit_h2(ex["heading"])
            _render_markdown_body(story, ex["body"], styles)
            for ss in ex.get("subsections", []):
                story.append(pdf_lib.para(ss["heading"],
                                           styles["h3"] if ss["level"] <= 3 else styles["h4"]))
                _render_markdown_body(story, ss["body"], styles)

        # Вставляем готовый TOC сразу после обложки (P1.5): записи собраны
        # за время рендера, поэтому отражают именно отрисованные секции
        # (с учётом recipient-гейтов) — без предсказания и рассинхрона.
        # Первой строкой TOC — быстрый переход к началу документа (стр. 1).
        if "toc" not in drop:
            toc_entries.insert(0, ("В начало", "doc-top"))
            toc_flows = _build_toc(toc_entries, styles)
            for i, f in enumerate(toc_flows):
                story.insert(cover_end + i, f)

        # Схлопнуть случайные подряд идущие page-break'и (например, длинный TOC,
        # заканчивающийся разрывом, + leading-разрыв карты Stage 6 → пустая
        # страница). Без потери контента.
        story = _collapse_double_breaks(story)
        pdf_lib.build_doc(doc, story, with_background=True)
    finally:
        pdf_lib.clear_section_anchors()
        pdf_lib.set_footer_text("")
    return str(output_path)


# Человекочитаемые фразы для budget_status (вместо pipeline-ярлыков).
_BUDGET_STATUS_RU = {
    "under_target": "в рамках бюджета",
    "on_target": "в рамках бюджета",
    "over_10_20": "превышение бюджета на 10–20%",
    "over_20+": "превышение бюджета более чем на 20%",
}


def _implied_budget_status(total: float, target: float) -> str:
    """Статус бюджета, который следует из сырых total/target (пороги §6.5).

    Если расходится с YAML `budget_status` — значит охваты total и target
    различны (in-trip vs all-in), и прямое «факт vs план» на обложке вводит
    в заблуждение (G3).
    """
    if not target:
        return "on_target"
    r = total / target
    if r <= 0.9:
        return "under_target"
    if r < 1.1:
        return "on_target"
    if r < 1.2:
        return "over_10_20"
    return "over_20+"


def _is_budget_title(title: str) -> bool:
    """Подсекция «Сводных таблиц» про бюджет (для пометки авторитетности)."""
    return "бюджет" in (title or "").lower()


def _build_route_string(groups: list["RegionGroup"]) -> str:
    """Маршрут регионами через стрелки: «Сеул → Сораксан → ... → Сеул».

    Базовые имена регион-групп по порядку (суффиксы «(прилёт)/(финал)»
    срезаются), соседние одинаковые схлопываются.
    """
    bases: list[str] = []
    for g in groups:
        base = re.sub(r"\s*\([^)]*\)\s*$", "", g.name).strip()
        if not bases or bases[-1] != base:
            bases.append(base)
    return " → ".join(bases)


_TEMPO_RE = re.compile(
    r"темп[ауе]?\s*[:—-]?\s*([A-Za-zА-Яа-я]+(?:\s*\([^)]*\))?)",
    re.IGNORECASE,
)


def _extract_tempo(context_body: str) -> str | None:
    """Извлечь темп из тела контекста (если упомянут).

    Отсекаем ложные совпадения («темпе и транспорте» → «и») — принимаем
    только значение, похожее на реальный темп.
    """
    m = _TEMPO_RE.search(context_body)
    cand = m.group(1).strip() if m else None
    return cand if cover_common.looks_like_tempo(cand) else None


# Тезис «Замысел маршрута» (#14, Этап-2): опц. первая строка `## Контекст…`.
# Рендер выносит его на обложку; из тела контекста строка вырезается, чтобы
# не дублироваться у фронта. Backward-compat: отсутствует → cover как раньше.
_THESIS_RE = re.compile(
    r"^\s*\**\s*Замысел\s+маршрута\b\s*[:.]?\s*\**\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_thesis(context_body: str) -> str | None:
    """Достать текст тезиса «Замысел маршрута» из тела контекста (или None)."""
    m = _THESIS_RE.search(context_body or "")
    if not m:
        return None
    text = m.group(1).strip()
    return text or None


def _strip_thesis_line(context_body: str) -> str:
    """Удалить строку тезиса из тела контекста (чтобы не рендерить дважды)."""
    return _THESIS_RE.sub("", context_body, count=1).lstrip("\n")


# Цвета статус-чипов дня (Этап-2): амбер «план», зелёный «забронировано»,
# синий «погода» — 3-цветная статус-кодировка из дизайн-ревью.
def _day_status_chips(day: "DayBlock") -> list[tuple[str, str, str]]:
    """Собрать (label, fg, bg) чипы дня из booking/weather маркеров."""
    C = pdf_lib.COLORS
    chips: list[tuple[str, str, str]] = []
    if day.booking:
        # Бронь (план/подтверждено) — teal-тинт чип (дизайн-язык .chip--book).
        chips.append((f"бронь: {day.booking}", C["chip_book_fg"], C["chip_book_bg"]))
    for w in day.weather:
        # Погода — синий тинт (.chip--weather), НЕ кричащий синий.
        chips.append((f"погода: {w}", C["chip_weather_fg"], C["chip_weather_bg"]))
    return chips


def _cover_budget_note(cover: dict) -> str | None:
    """Бюджетная сноска обложки (под статбендом). Расхождение охвата (G3):
    поездка vs план all-in — честная расшифровка; иначе факт/план; иначе фраза.
    """
    if not cover.get("budget_status"):
        return None
    total = cover.get("total_budget_rub")
    target = cover.get("budget_target_rub")
    note = _BUDGET_STATUS_RU.get(str(cover["budget_status"]), str(cover["budget_status"]))
    if total and target:
        mismatch = (cover.get("home_eq_start") is False
                    or _implied_budget_status(total, target) != str(cover["budget_status"]))
        if mismatch:
            note += f" (поездка ~{total:,} ₽ · план all-in ~{target:,} ₽)".replace(",", " ")
        else:
            note += f" (факт {total:,} ₽ · план {target:,} ₽)".replace(",", " ")
    return note


def _build_cover_page(
    story, cover: dict, title: str | None, styles,
    *, route: str = "", tempo: str | None = None, thesis: str | None = None,
    ribbon_stops: list[tuple[str, str]] | None = None,
    stat_rows: list[tuple[str, str, str]] | None = None,
    show_todo_count: bool = True,
    show_variant: bool = True,
    show_budget_note: bool = True,
) -> None:
    """Render hero-обложки: кикер + человеческий заголовок + тезис-курсив +
    лента маршрута + статбенд + компактный паспорт (дизайн-язык).

    `show_variant=False` убирает из кикера «Вариант X», `show_budget_note=False`
    — подстрочник с вердиктом о попадании в бюджет: в поездке варианта уже нет,
    а бюджет либо сойдётся по факту, либо нет — защищать план не перед кем.

    `show_todo_count=False` убирает с обложки строку «Пунктов к проверке»:
    счётчик обязан жить вместе с тем, что считает. В дорожном PDF секции «TODO
    для верификации» нет (`TRIP_DROP_PROGRESS`), и обложка обещала 27 пунктов,
    которых в документе не найти."""
    # Кикер над заголовком: ФИНАЛЬНЫЙ ПЛАН · ВАРИАНТ X · [РЕТРОСПЕКТИВА].
    variant_letter = _variant_letter(cover) if show_variant else ""
    kicker_bits = ["Финальный план"]
    if variant_letter:
        kicker_bits.append(f"Вариант {variant_letter}")
    if cover.get("retrospective"):
        kicker_bits.append("Ретроспектива")
    kicker_para = pdf_lib.cover_kicker(" · ".join(kicker_bits))
    # Кикер — первый flowable: на нём destination `doc-top` + outline «В начало»
    # (прыжок «В начало» ведёт на самый верх документа).
    kicker_para._dest_slug = "doc-top"          # type: ignore[attr-defined]
    kicker_para._outline_title = "В начало"     # type: ignore[attr-defined]
    kicker_para._outline_level = 0              # type: ignore[attr-defined]
    story.append(kicker_para)

    # Человеческий заголовок (страна из trip_id, без pipeline-жаргона).
    story.append(pdf_lib.para(_human_cover_title(cover), styles["cover_title"]))

    # Тезис «Замысел маршрута» (#14) — курсивом как подзаголовок-идея.
    if thesis:
        story.append(pdf_lib.para(
            f"*{thesis}*", styles["cover_subtitle"], highlight_todo=False,
        ))

    # Лента маршрута (точки баз + ночи).
    if ribbon_stops:
        story.append(pdf_lib.spacer(12))
        story.append(pdf_lib.route_ribbon(ribbon_stops))
    # Статбенд (крупные показатели: длительность / даты / базы / бюджет).
    if stat_rows:
        story.append(pdf_lib.spacer(6))
        story.append(pdf_lib.stat_band(stat_rows))

    # Бюджетная сноска под статбендом: при расхождении охвата (поездка vs
    # план all-in, G3) — честная расшифровка мелким; иначе факт/план.
    budget_note = _cover_budget_note(cover) if show_budget_note else None
    if budget_note:
        story.append(pdf_lib.spacer(3))
        story.append(pdf_lib.para(budget_note, styles["small"], highlight_todo=False))

    # Компактный паспорт — только то, чего нет в ленте/статбенде
    # (Кто едет / Темп / Пунктов к проверке).
    rows: list[tuple[str, str]] = []
    who = cover.get("who_goes") or cover_common.profile_name(cover.get("travelers_profile"))
    if who:
        rows.append(("Кто едет", who))
    if tempo:
        rows.append(("Темп", tempo))
    if show_todo_count and cover.get("todo_items_count"):
        rows.append(("Пунктов к проверке", f"{cover['todo_items_count']}"))
    if rows:
        story.append(pdf_lib.spacer(10))
        story.append(pdf_lib.key_params_table(rows))


# Разбор заголовка дня: «День 1 (05.09 Сб). Старт маршрута: ...».
_DAY_HEADING_RE = re.compile(r"^День\s+(\d+)\s*(?:\(([^)]+)\))?\.?\s*(.*)$")
# Дата+день недели внутри скобок заголовка: «05.09 Сб».
_HEADING_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\s+([^\s)]+))?")
_MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
    12: "декабря",
}

# Кириллические гомоглифы букв вариантов → латиница. Stage 4 использует
# латинские A/B/C/D; Stage 5 YAML иногда даёт кириллицу (`chosen_variant_raw:
# "С"`) — нормализуем, чтобы «Вариант C» в обложке S5 совпадал со Stage 4 и не
# читался как «B».
_VARIANT_HOMOGLYPH = {
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Т": "T", "Х": "X", "Д": "D",
}


def _variant_letter(cover: dict) -> str:
    """Буква выбранного варианта (латиница) для обложки S5.

    Приоритет `chosen_variant_raw` («С» — буква как в Stage 4), затем
    `chosen_variant` («вариант_в»). Берём последний буквенный символ и
    нормализуем кириллический гомоглиф в латиницу.
    """
    raw = cover.get("chosen_variant_raw") or cover.get("chosen_variant") or ""
    s = str(raw).strip().strip('"').replace("вариант_", "").replace("_", " ")
    letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", s)
    if not letters:
        return ""
    ch = letters[-1].upper()
    return _VARIANT_HOMOGLYPH.get(ch, ch)


def _split_day_heading(heading: str) -> tuple[str, str]:
    """Вернуть (bar_label, subtitle) из заголовка дня.

    bar_label — «День N · DD.MM» (дата попадает в PDF-outline → ориентир по
    дате, а не только по номеру);
    subtitle  — «DD месяца (Дн): Описание» (человекочитаемая дата + краткий
    день недели + двоеточие, без ведущей точки).

    Источник — сырой заголовок `### День N (DD.MM Дн). Описание`. Если дата не
    в формате DD.MM (например, polished «День N · суббота, 5 сентября · …») —
    мягкий фолбэк на старое поведение.
    """
    m = _DAY_HEADING_RE.match(heading.strip())
    if not m:
        return heading, ""
    num, date, title = m.group(1), (m.group(2) or ""), (m.group(3) or "").strip()
    dm = _HEADING_DATE_RE.search(date) if date else None
    if not dm:
        # Нет распознаваемой DD.MM — старое поведение (graceful).
        bar = f"День {num}" + (f" — {date}" if date else "")
        return bar, title
    dd, mm, wd = int(dm.group(1)), int(dm.group(2)), (dm.group(3) or "").strip()
    bar = f"День {num} · {dd:02d}.{mm:02d}"
    human = f"{dd} {_MONTHS_GEN.get(mm, '')}".strip()
    wd_part = f" ({wd})" if wd else ""
    subtitle = f"{human}{wd_part}: {title}" if title else f"{human}{wd_part}"
    return bar, subtitle


def _build_region_color_map(days: list[DayBlock]) -> dict[str, str]:
    """Назначить цвет каждому региону по порядку первого появления.

    Пусто, если polish не проставил регионы (graceful — плашки без полос).
    """
    from export.style import REGION_PALETTE  # локальный импорт: избегаем цикла
    mapping: dict[str, str] = {}
    for d in days:
        if d.region and d.region not in mapping:
            mapping[d.region] = REGION_PALETTE[len(mapping) % len(REGION_PALETTE)]
    return mapping


@dataclass
class RegionGroup:
    """Группа последовательных дней одного региона (для сводной таблицы/titler)."""
    name: str
    days: list[DayBlock]
    fields: dict = field(default_factory=dict)  # база/главное/буфер/бронь/риск/бюджет

    @property
    def main(self) -> str | None:
        return self.fields.get("главное")

    @property
    def budget(self) -> str | None:
        return self.fields.get("бюджет")


def _day_date(day: DayBlock) -> str:
    """Достать дату «DD.MM» из заголовка дня (без дня недели)."""
    m = re.search(r"\((\d{2}\.\d{2})", day.heading)
    return m.group(1) if m else ""


# Парсинг бюджета дня — валюта-агностичный (₩ / ₽ / $ / € / ₫ / ₭ / ៛ / £).
# Берём ПЕРВИЧНУЮ сумму до «(» (в скобках обычно конвертация/комментарий),
# извлекаем числовой диапазон и валютный символ + его позицию (префикс/суффикс).
_CUR_SYMBOLS = "\u20a9\u20bd$\u20ac\u20ab\u20ad\u17db\u00a3"  # ₩₽$€₫₭៛£
_BUDGET_NUM_RE = re.compile(r"\d[\d.,\s\u00a0]*")


def _parse_budget_range(text: str):
    """Бюджет дня → (low, high, symbol, prefix) или None.

    `prefix=True` — символ валюты стоит перед суммой (₩35 000), иначе после
    (35 000 ₽). Конвертация/текст в скобках игнорируются.
    """
    head = text.split("(", 1)[0]
    sym = next((c for c in head if c in _CUR_SYMBOLS), None)
    if sym is None:
        return None
    nums = _BUDGET_NUM_RE.findall(head)
    vals = []
    for n in nums:
        cleaned = re.sub(r"[.,\s\u00a0]", "", n)
        if cleaned:
            vals.append(int(cleaned))
    if not vals:
        return None
    first_digit = re.search(r"\d", head)
    prefix = head.index(sym) < first_digit.start()
    return (vals[0], vals[-1], sym, prefix)


def _fmt_amount(value: int) -> str:
    """Число с пробелами-разделителями тысяч."""
    return f"{value:,}".replace(",", "\u00a0")


def _nbsp_budget(s: str) -> str:
    """Защитить бюджет-строку от переноса посреди числа.

    Источник строки бывает разный: computed `_region_budget_range`
    (уже с nbsp в разрядах) или сырое поле маркера региона
    `[[регион: … | бюджет: ~₩75 000–110 000]]` с обычными пробелами.
    Нормализуем единообразно на рендере:
      • пробел между цифрами (разряды тысяч) → неразрывный — число не рвётся;
      • дефис/тире в диапазоне → en-dash без пробелов — перенос допустим
        только ПОСЛЕ тире, не посреди числа («~₩75 000–110 ⏎ 000» больше
        не возникает).
    Идемпотентна.
    """
    if not s:
        return s
    s = re.sub(r"(?<=\d)\s+(?=\d)", " ", s)
    s = re.sub(r"(?<=\d)\s*[-–—]\s*(?=\d)", "–", s)
    return s


def _region_budget_range(group: "RegionGroup"):
    """Сумма дневных бюджетов региона как диапазон (без жилья/межгорода).

    Валюта берётся из дневных 💰-маркеров (любая). Если ни один день не дал
    суммы — None (тогда используется поле маркера, если задано).
    """
    lo = hi = 0
    sym = None
    prefix = True
    found = False
    for d in group.days:
        budget_marker = next((m.content for m in d.markers if m.icon == "\U0001f4b0"), "")
        rng = _parse_budget_range(budget_marker)
        if rng:
            lo += rng[0]
            hi += rng[1]
            sym = sym or rng[2]
            prefix = rng[3]
            found = True
    if not found or sym is None:
        return None
    if lo == hi:
        body = _fmt_amount(lo)
    else:
        body = f"{_fmt_amount(lo)}\u2013{_fmt_amount(hi)}"
    return f"~{sym}{body}" if prefix else f"~{body}\u00a0{sym}"


def group_regions(days: list[DayBlock]) -> list[RegionGroup]:
    """Сгруппировать дни в последовательные регион-раны.

    Регион меняется → новая группа (Сеул в начале и в конце — две группы).
    Пусто, если регионы не размечены.
    """
    groups: list[RegionGroup] = []
    for d in days:
        if not d.region:
            continue
        if groups and groups[-1].name == d.region:
            groups[-1].days.append(d)
        else:
            groups.append(RegionGroup(name=d.region, days=[d]))
    # Поля региона берём из первого дня группы, где маркер их содержит
    # (обычно у дня входа в регион).
    for g in groups:
        merged: dict = {}
        for dd in g.days:
            for k, v in dd.region_fields.items():
                merged.setdefault(k, v)
        # Бюджет региона — считаем диапазоном из дневных 💰 (предпочтительно
        # перед статичным полем маркера; пользователь хочет видеть вилку).
        computed = _region_budget_range(g)
        if computed:
            merged["бюджет"] = computed
        g.fields = merged
    return groups


# Порядок и метки bullet'ов в titler-блоке региона (из полей маркера).
_TITLER_BULLET_ORDER = [
    ("главное", "Главное"),
    ("буфер", "Буфер"),
    ("бронь", "Бронь заранее"),
    ("риск", "Риск"),
    ("бюджет", "Бюджет региона"),
]


def _region_titler_bullets(fields: dict) -> list[tuple[str, str]]:
    """Собрать (label, value) для titler из полей маркера в фикс. порядке."""
    out: list[tuple[str, str]] = []
    for key, label in _TITLER_BULLET_ORDER:
        if fields.get(key):
            value = fields[key]
            if key == "бюджет":
                value = _nbsp_budget(value)
            out.append((label, value))
    return out


def _build_region_summary(story, groups: list[RegionGroup], styles) -> None:
    """Сводная таблица регионов с кликабельными ссылками на дни.

    Колонки: Регион | Дни | Даты | Ночи | Главное | Бюджет региона.
    Номера дней — отдельные anchor-ссылки `[N](#dayN)`.
    """
    if not groups:
        return
    # Даты по регионам; если ни у одного нет — колонку «Даты» не показываем.
    region_dates: list[str] = []
    for g in groups:
        dl = [x for x in (_day_date(d) for d in g.days) if x]
        region_dates.append(f"{dl[0]}–{dl[-1]}" if len(dl) > 1 else (dl[0] if dl else ""))
    has_dates = any(region_dates)

    if has_dates:
        header = ["Регион", "Дни", "Даты", "Ночи", "Главное", "Бюджет"]
        col_widths = ["16%", "14%", "14%", "9%", "30%", "17%"]
    else:
        header = ["Регион", "Дни", "Ночи", "Главное", "Бюджет"]
        col_widths = ["18%", "16%", "9%", "37%", "20%"]
    rows = [header]
    for gi, g in enumerate(groups, start=1):
        nums = [d.day_num for d in g.days if d.day_num]
        # Каждый день — отдельная кликабельная ссылка, через «–».
        days_links = "–".join(f"[{n}](#day{n})" for n in nums)
        nights = str(len(g.days))  # приближённо: 1 день ≈ 1 ночь в регионе
        # Имя региона — ссылка на его titler-плашку (#region-{gi}).
        name_link = f"[{g.name}](#region-{gi})"
        row = [name_link, days_links]
        if has_dates:
            row.append(region_dates[gi - 1])
        row += [nights, g.main or "", _nbsp_budget(g.budget or "")]
        rows.append(row)
    story.append(pdf_lib.spacer(4))
    story.append(pdf_lib.data_table(rows, header=True, col_widths=col_widths))
    story.append(pdf_lib.spacer(6))


def _render_day(
    story, day: DayBlock, styles, *, recipient: str,
    region_colors: dict[str, str] | None = None,
    has_region_summary: bool = False,
) -> None:
    """Render одного дня: тёмная плашка-заголовок + бюджет в углу + тело."""
    region_colors = region_colors or {}
    # Бюджет (💰) выносим в правый угол плашки, из тела убираем.
    budget_text: str | None = None
    body_markers: list[DayMarker] = []
    for m in day.markers:
        if m.icon == "💰":
            budget_text = _nbsp_budget(m.content.strip()) or None
        else:
            body_markers.append(m)

    bar_label, subtitle = _split_day_heading(day.heading)
    slug = f"day{day.day_num}" if day.day_num else None
    # День-переезд: эвристика по заголовку или 📍-маркеру с «→».
    is_transfer = ("переезд" in (day.heading or "").lower()) or any(
        (mk.icon == "📍") and ("→" in (mk.content or "")) for mk in day.markers)
    story.append(pdf_lib.day_header_bar(
        bar_label, subtitle,
        anchor_slug=slug,
        outline_level=1 if slug else None,
        region=day.region,
        region_color=region_colors.get(day.region) if day.region else None,
        transfer=is_transfer,
    ))

    # Статус-чипы дня (Этап-2): бронь / погода. Пусто → ничего (backward-compat).
    chips = pdf_lib.status_chips(_day_status_chips(day))
    if chips is not None:
        story.append(chips)

    if day.intro:
        _render_markdown_body(story, day.intro, styles)
    for marker in body_markers:
        # parents: ⚠️-блоки скрыты adapter'ом, но на всякий случай чек.
        if recipient == "parents" and marker.icon in ("⚠️", "⚠"):
            continue
        _render_marker(story, marker, styles)
    # Подвал дня: бюджет (вынесен из шапки в day-foot, дизайн-язык `.day-foot`).
    if budget_text:
        story.append(pdf_lib.day_budget_line(budget_text))
    # Back-link на сводную таблицу регионов (только если она есть).
    if has_region_summary:
        story.append(pdf_lib.para(
            "[↑ К сводной таблице](#regions-summary)", styles["small"],
            highlight_todo=False,
        ))
    story.append(pdf_lib.spacer(8))


# Sub-header'ы внутри «Контекст и ключевые параметры», которые надо
# сохранить (всё до первого из них — интро-параметры — выкидывается, т.к.
# дублирует обложку).
_CTX_LOGIC_RE = re.compile(r"логика\s+ключевых\s+решени", re.IGNORECASE)
_CTX_EXCLUDED_RE = re.compile(r"чего\s+(больше\s+)?нет\s+в\s+маршрут", re.IGNORECASE)


def _parse_context_parts(context_body: str) -> dict:
    """Разобрать «Контекст» на части для РАЗДЕЛЬНОГО размещения (P1.2).

    Интро-параметры (Поездка/Вариант/Бюджет/Mode/...) выкидываются — они уже
    в таблице обложки. Остальное делится на два независимо размещаемых куска:

      - `excluded_rows`: list[[место, причина]] — «Чего нет в маршруте» →
        рендерится У ФРОНТА (после обложки/карты), это краткие исключения;
      - `logic_blocks`: list[list[str]] — «Логика ключевых решений» →
        рендерится в ПРИЛОЖЕНИИ в конце (review-слой, для self).
      - `fallback`: str | None — если структуру не нашли, весь body
        (рендерится у фронта как раньше — ничего не теряем).
    """
    blocks = _split_md_blocks(context_body)
    start = None
    for i, blk in enumerate(blocks):
        if _CTX_LOGIC_RE.search(" ".join(blk)):
            start = i
            break
    if start is None:
        return {"logic_blocks": [], "excluded_rows": [], "fallback": context_body}

    mode = "logic"  # logic | excluded
    logic_blocks: list[list[str]] = []
    excluded_rows: list[list[str]] = []
    for blk in blocks[start:]:
        joined = " ".join(blk)
        is_logic_hdr = _CTX_LOGIC_RE.search(joined) and _is_sub_header_block(blk)
        is_excl_hdr = _CTX_EXCLUDED_RE.search(joined) and _is_sub_header_block(blk)
        if is_excl_hdr:
            mode = "excluded"
            continue
        if is_logic_hdr:
            continue
        if mode == "excluded":
            if _is_bullet_block(blk):
                for item in _parse_bullets(blk):
                    place, reason = _split_excluded_item(item)
                    excluded_rows.append([place, reason])
            # не-bullet текст в excluded-режиме обычно отсутствует — игнор.
        else:
            logic_blocks.append(blk)
    return {"logic_blocks": logic_blocks, "excluded_rows": excluded_rows,
            "fallback": None}


def _render_excluded_front(story, parts: dict, styles, *,
                           drop_excluded: bool = False) -> None:
    """«Чего нет в маршруте и почему» — у фронта (после обложки).

    Краткие исключения (таблица «Место | Причина») остаются вперёд: читатель
    видит контур решений до операционного контента. Глубокий рационал —
    отдельно, в приложении (см. `_render_decision_logic`).
    """
    if parts.get("fallback"):
        _render_markdown_body(story, parts["fallback"], styles)
        return
    # В дорожном документе таблица исключений не нужна: она объясняет
    # решения, которые уже приняты. «Контекст» (fallback выше) остаётся.
    rows = [] if drop_excluded else (parts.get("excluded_rows") or [])
    if not rows:
        return
    story.append(pdf_lib.spacer(6))
    story.append(pdf_lib.para("Чего нет в маршруте и почему", styles["h4"],
                               highlight_todo=False))
    story.append(pdf_lib.spacer(2))
    story.append(pdf_lib.data_table(
        [["Место", "Причина исключения"], *rows], header=True,
    ))


def _render_decision_logic(story, parts: dict, styles) -> None:
    """«Логика ключевых решений» — в приложении, в конце документа (P1.2).

    Review-слой: уходит в тыл, чтобы фронт открывался рамкой→картой→днями,
    а не обоснованиями. Для полевой версии (recipient=field) и parents не
    рендерится (гейт в build_pdf).
    """
    for blk in parts.get("logic_blocks") or []:
        _render_markdown_body(story, "\n".join(blk), styles)


def _split_excluded_item(item: str) -> tuple[str, str]:
    """Разбить пункт «Чего нет» на (место, причина) по первому « — »."""
    parts = re.split(r"\s+—\s+", item, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return item.strip(), ""


# Паттерн «голая bold-метка» вида `**Программа:**` (без текста после).
# Используется чтобы НЕ рендерить её отдельным параграфом перед bullets:
# `🎯 **Программа:** \n - bullet 1` → label + bullets, без дублирования.
_BOLD_LABEL_RE = re.compile(r"^\*\*([^*\n]+):\*\*\s*$")


def _strip_leading_label(text: str, label: str) -> str:
    """Срезать ведущий bold-токен тела, дублирующий метку-лид маркера.

    Билдер сам рендерит метку `{label}.` перед телом. Если тело начинается
    с того же слова жирным (`**Программа** (...)`, `**Программа:**`,
    `**Программа** — …`) — это дубль: срезаем bold-токен и следующий за ним
    разделитель (двоеточие/тире/точку), оставляя содержательный хвост.
    Слово сравнивается с меткой без учёта регистра. Иначе — текст без правок.
    """
    m = re.match(r"^\*\*\s*([^*\n]+?)\s*\*\*", text)
    if not m:
        return text
    word = m.group(1).strip().rstrip(":").strip()
    if word.casefold() != label.casefold():
        return text
    rest = text[m.end():]
    return re.sub(r"^\s*[:.—–-]?\s*", "", rest)


def _render_marker(story, marker: DayMarker, styles) -> None:
    """Render один marker-блок (Локация / Отель / Программа / Бюджет / Риски).

    Emoji (📍/🏨/🎯/💰/⚠️) НЕ рендерятся: их нет в DejaVu/macOS Arial.
    Вместо них — цветная жирная метка-слово (Локация / Отель / ...) в
    primary-цвете, для риска — в danger-цвете.

    Если intro-часть — это «голая» bold-метка вида `**Программа:**`
    (без содержательного текста после), она дублирует метку маркера и
    пропускается — иначе получаем `**Программа.** **Программа:**`
    перед bullet-списком.
    """
    # «Риски» (⚠) — отдельный заметный прямоугольник (warning_box),
    # а не просто красное слово. Бросается в глаза, но не кричит.
    if marker.icon in ("⚠️", "⚠"):
        story.append(pdf_lib.spacer(2))
        story.append(pdf_lib.warning_box(marker.content.strip(), styles))
        story.append(pdf_lib.spacer(2))
        return

    intro, bullets = split_bullets_and_intro(marker.content)
    # Если intro = `**Label:**` на одной строке — это просто sub-header
    # для bullets, выкидываем (label маркера уже даёт ту же информацию).
    if bullets and intro and _BOLD_LABEL_RE.match(intro.strip()):
        intro = ""

    color = pdf_lib.COLORS["primary"]
    intro_lines = intro.splitlines() if intro else []
    first_line = intro_lines[0] if intro_lines else ""
    # Тело может начинаться с того же слова жирным (`**Программа** (...)`),
    # дублируя метку-лид `{label}.`, которую билдер добавит ниже. Срезаем.
    first_line = _strip_leading_label(first_line, marker.label)
    rest_intro = "\n".join(intro_lines[1:]).strip() if len(intro_lines) > 1 else ""

    story.append(pdf_lib.labeled_para(
        f"{marker.label}:", first_line, styles["day_marker"], color=color,
    ))
    if rest_intro:
        _render_markdown_body(story, rest_intro, styles, base_style="day_marker")
    if bullets:
        # bullets под day-marker (например, под 🎯 Программа) — всегда
        # bullet-list, потому что они под именованной меткой (label маркера
        # выступает sub-header'ом).
        _render_bullets_smart(story, bullets, styles, force_bullets=True)


def _render_blocks(story, blocks: list[dict], styles) -> None:
    """Render result of extract_tables_and_text — text + table блоки."""
    for block in blocks:
        if block["type"] == "text":
            _render_markdown_body(story, block["content"], styles)
        elif block["type"] == "table":
            story.append(pdf_lib.spacer(4))
            story.append(pdf_lib.data_table(block["rows"], header=True))
            story.append(pdf_lib.spacer(6))


# Совпадает с горизонтальной чертой markdown (`---`, `----`, ...).
_HR_RE = re.compile(r"^-{3,}\s*$")

# Паттерн «определение»: bullet вида `**Key:** value` — рендерится как
# definition-list, а не bullet-list.
_DEFINITION_BULLET_RE = re.compile(r"^\*\*([^*\n]+):\*\*\s+(.+)$", re.DOTALL)

# Bullet, начинающийся с **bold** — частый паттерн в Stage 5 для
# narrative-параграфов внутри списков key-value-like блоков.
_BOLD_LEAD_BULLET_RE = re.compile(r"^\*\*([^*\n]+?)\*\*([\s\S]*)$")

# «Sub-header» внутри секции — отдельный bold-параграф (одна строка,
# заканчивается на `:` или `**`). Указывает, что следующий bullet-список
# семантически — sub-list под этим заголовком и должен ОСТАВАТЬСЯ
# bullet'ами (а не сплющиваться в параграфы).
_SUB_HEADER_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*[:.]?\s*$")
_SUB_HEADER_WITH_TRAIL = re.compile(r"^\s*\*\*[^*\n]+\*\*\s*[^*\n]*[:.]?\s*$")

# Маркер warning'а в начале блока — `⚠️ ...` / `⚠ ...`. Содержимое блока
# целиком рендерится в warning_box (красная рамка), сам символ срезается
# (рамка уже даёт визуальный сигнал).
_WARNING_LEAD_RE = re.compile(r"^\s*⚠️?\s+(.+)$", re.DOTALL)


def _is_bullet_block(block: list[str]) -> bool:
    """Все непустые строки начинаются с `- ` или с отступа (continuation)."""
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


def _is_sub_header_block(block: list[str]) -> bool:
    """Один-два строчный bold-заголовок (вида `**Heading:**` или
    `**Heading** (note):`).
    """
    real_lines = [ln for ln in block if ln.strip()]
    if not (1 <= len(real_lines) <= 2):
        return False
    joined = " ".join(real_lines).strip()
    # должен начинаться с `**`, содержать только одну bold-пару,
    # не должен содержать переходов на следующую мысль (длинных не-bold-фраз).
    if not joined.startswith("**"):
        return False
    # Грубая эвристика: длина ≤ ~120 символов, заканчивается на `:` или `**`.
    if len(joined) > 120:
        return False
    if not (joined.endswith(":") or joined.endswith("**")
            or joined.endswith(":**") or joined.endswith("**:")
            or joined.endswith(").") or joined.endswith("):")):
        return False
    return True


def _parse_bullets(block: list[str]) -> list[str]:
    """Достать сами пункты из bullet-блока, склеив multi-line items."""
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


def _render_markdown_body(
    story, body: str, styles, *, base_style: str = "body", air: bool = False,
) -> None:
    """Рендер markdown-body: параграфы / списки / таблицы / подзаголовки.

    `air=True` (для приложений Stage 6 — досье / углубления): добавляет
    дополнительный вертикальный отбой после прозы / bullet-групп / под-
    заголовков, чтобы справочный текст не читался «сплошняком». На рендер
    дней Stage 5 не влияет (по умолчанию `air=False`).

    Bullet-логика контекстно-зависимая:
      - Список, идущий ПОСЛЕ `**Sub-header:**` блока, остаётся bullets
        (это sub-list пояснений под заголовком).
      - Список, идущий top-level в секции, со ВСЕМИ пунктами на `**bold**` —
        сплющивается в параграфы / definition-list (визуально не зашумляет).
      - Список с регулярными items без `**bold**` лидов — обычные bullets.

    `⚠️ ...` / `⚠ ...` в начале блока → warning_box (красная рамка).
    `> ...` блок → info_box (амбер рамка).
    `---` — горизонтальные черты markdown-источника — пропускаются (роль
    выполняют page break'и между H2).
    """
    if not body or not body.strip():
        return
    blocks = _split_md_blocks(body)
    style = styles[base_style]

    prev_was_sub_header = False
    for block in blocks:
        if not block:
            continue
        # Горизонтальные черты — drop.
        if all(_HR_RE.match(ln) or not ln.strip() for ln in block):
            continue
        first = block[0]

        # Warning-блок (`⚠ ...` / `⚠️ ...` в начале).
        # Тестируем ДО blockquote, чтобы случай `> ⚠️ ...` тоже сработал
        # по приоритету blockquote (info-box) — а самостоятельный ⚠ —
        # как warning.
        m_warn = _WARNING_LEAD_RE.match(" ".join(block))
        if first.lstrip().startswith("⚠") and m_warn:
            text = m_warn.group(1).strip()
            story.append(pdf_lib.warning_box(text, styles))
            story.append(pdf_lib.spacer(4))
            prev_was_sub_header = False
            continue

        # Блок-цитата (`> текст`) → info-box.
        if all(ln.lstrip().startswith(">") or not ln.strip() for ln in block):
            stripped = " ".join(
                ln.lstrip(" ").lstrip(">").lstrip() for ln in block if ln.strip()
            )
            story.append(pdf_lib.info_box(stripped, styles))
            story.append(pdf_lib.spacer(4))
            prev_was_sub_header = False
            continue

        # H4-заголовок (`#### `).
        if first.startswith("#### "):
            story.append(pdf_lib.para(first[5:].strip(), styles["h4"]))
            if air:
                story.append(pdf_lib.spacer(2))
            remainder = block[1:]
            if remainder:
                _render_markdown_body(story, "\n".join(remainder), styles,
                                       base_style=base_style, air=air)
            prev_was_sub_header = True
            continue

        # GFM-таблица.
        if len(block) >= 2 and "|" in first and _TABLE_DELIM_RE.match(block[1]):
            story.append(pdf_lib.spacer(4))
            story.append(pdf_lib.data_table(
                [_split_md_row(l) for l in block if "|" in l and not _TABLE_DELIM_RE.match(l)],
                header=True,
            ))
            story.append(pdf_lib.spacer(6))
            prev_was_sub_header = False
            continue

        # Sub-header (single bold line, `**Логика ключевых решений:**`).
        # Рендерим как H4-paragraph; следующий bullet-list под ним
        # ОСТАЁТСЯ bullets, не сплющивается.
        if _is_sub_header_block(block):
            joined = " ".join(ln.strip() for ln in block if ln.strip())
            # Убираем обрамляющие `**` и хвостовое `:` — стиль h4 сам выделит.
            cleaned = re.sub(r"^\*\*|\*\*$|\*\*\s*:\s*$|:\s*$", "", joined.strip())
            cleaned = cleaned.replace("**", "")
            story.append(pdf_lib.para(cleaned, styles["h4"], highlight_todo=False))
            if air:
                story.append(pdf_lib.spacer(2))
            prev_was_sub_header = True
            continue

        # Bullet-list (или definition-list).
        if _is_bullet_block(block):
            items = _parse_bullets(block)
            if items:
                _render_bullets_smart(
                    story, items, styles,
                    base_style=base_style,
                    force_bullets=prev_was_sub_header,
                )
            if air:
                story.append(pdf_lib.spacer(3))
            prev_was_sub_header = False
            continue

        # Регулярный параграф.
        text = " ".join(ln.strip() for ln in block)
        story.append(pdf_lib.para(text, style))
        if air:
            story.append(pdf_lib.spacer(3))
        prev_was_sub_header = False


def _render_bullets_smart(
    story, items: list[str], styles, *, base_style: str = "body",
    force_bullets: bool = False,
) -> None:
    """Выбрать визуальный формат для bullet-блока.

    Логика:
      - `force_bullets=True` (вызов из контекста после sub-header'а) —
        всегда рендерим bullet-list (это пояснения под заголовком).
      - Все пункты совпали с `**Key:** value` → definition-list
        (фактическая таблица «ключ-значение», без bullet-маркеров).
      - Все пункты начинаются с `**bold**` лидов (но `:` НЕ внутри) →
        flat paragraphs с сохранённым bold (визуально структурно, но
        без bullet'ов — снимает «всё bullets» эффект в Контексте/Шапке).
      - Иначе → обычный bullet-list.
    """
    if force_bullets:
        story.extend(pdf_lib.bullet_list(items, styles))
        return

    # Definition-list — точное совпадение `**Key:** value`.
    def_matches = [_DEFINITION_BULLET_RE.match(it.strip()) for it in items]
    if len(items) >= 2 and all(m is not None for m in def_matches):
        pairs = [(m.group(1).strip(), m.group(2).strip()) for m in def_matches]  # type: ignore[union-attr]
        story.extend(pdf_lib.definition_list(pairs, styles[base_style]))
        return

    # Bold-lead — пункты начинаются с `**bold**` (с двоеточием или без),
    # за которыми идёт текст. Рендерим как параграфы; bold сохраняется
    # внутри текста через md_inline_to_rl (он сам `**` → `<b>`).
    bold_matches = [
        _BOLD_LEAD_BULLET_RE.match(it.strip()) for it in items
    ]
    if len(items) >= 2 and all(m is not None for m in bold_matches):
        for it in items:
            story.append(pdf_lib.para(it.strip(), styles[base_style]))
        return

    # Дефолт — обычные bullets.
    story.extend(pdf_lib.bullet_list(items, styles))


def _split_md_blocks(text: str) -> list[list[str]]:
    """Разбить markdown на блоки по пустым строкам."""
    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for ln in lines:
        if ln.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(ln)
    if current:
        blocks.append(current)
    return blocks


# ---------------------------------------------------------------------------
# Renderer entry point + регистрация
# ---------------------------------------------------------------------------


def render_stage5(
    parsed: dict,
    *,
    recipient: str = "self",
    output_path: str | Path,
    **_kw: Any,
) -> "_renderer.RenderRequest":
    """Главный entry-point: распарсенный stage5 → PDF файл + RenderRequest.

    PDF пишется по `output_path`. Возвращается RenderRequest для logging /
    chat-presentation.
    """
    extracted = extract_content(
        parsed, input_path=[_kw.get("source_file"), output_path])
    pdf_path = build_pdf(extracted, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage": "5_final_plan",
            "trip_id": parsed.get("trip_id"),
            "recipient": recipient,
            "days_count": len(extracted["days"]),
            "todo_groups": len(extracted["todo"]),
        },
        metadata={
            "trip_id": parsed.get("trip_id"),
            "stage": parsed.get("stage"),
            "recipient": recipient,
            "font_family": pdf_lib._ACTIVE_FAMILY,
        },
        notes=[],
    )


# ---------------------------------------------------------------------------
# Adapter-extension: для родителей убрать ⚠️ из day-блоков
# ---------------------------------------------------------------------------


def _strip_warnings_in_days_for_parents(parsed_copy: dict) -> None:
    """Для recipient=parents — убрать ⚠️/⚠ блоки из day-секций.

    Generic-adapter уже выкидывает H2 «План реагирования на риски» целиком,
    но inline-⚠️ в днях остаются. Эта extension чистит их.
    """
    for sec in parsed_copy.get("sections") or []:
        if sec["heading"] != "Маршрут по дням":
            continue
        for day in sec.get("subsections") or []:
            body = day.get("body", "") or ""
            # Удаляем строки, начинающиеся на ⚠️ или ⚠, до следующего маркера/конца.
            lines = body.splitlines()
            cleaned: list[str] = []
            skip = False
            for ln in lines:
                if ln.startswith("⚠️") or ln.startswith("⚠"):
                    skip = True
                    continue
                if skip:
                    # Продолжаем skip до пустой строки или следующего маркера.
                    if not ln.strip():
                        skip = False
                        cleaned.append(ln)
                        continue
                    if _MARKER_LINE_RE.match(ln):
                        skip = False
                        cleaned.append(ln)
                    # иначе — внутри ⚠️-блока, пропускаем
                    continue
                cleaned.append(ln)
            day["body"] = "\n".join(cleaned)


# Регистрация — выполняется при импорте модуля.
_renderer.register_renderer("5_final_plan", "pdf", render_stage5)
_adapter.register_stage_extension("parents", "5_final_plan", _strip_warnings_in_days_for_parents)

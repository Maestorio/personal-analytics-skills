"""docx_lib.py — общие DOCX-примитивы для editable экспортов.

**Контракт формата** артефакта-источника (сейчас Stage 3: POI-карточки, теги,
комментарии) — канон `references/stage3/stage3-output-spec.md`; сверка —
`tests/test_format_contract.py`.

DOCX-аналог `pdf_lib.py`: helpers нижнего уровня (bookmark / hyperlink /
shading / borders) + примитивы верхнего уровня (anketa-style choice
question, text input field, POI card, region header, cluster header).

Используется сейчас Stage 3 export; будет переиспользоваться будущими
DOCX-стадиями (если/когда появятся).

Принципы:
  - Без python-docx Content Controls (SDT) с placeholder — пользователю
    приходится постоянно стирать серый текст. Вместо них anketa-style:
    `[ ]` checkbox-маркеры для multi-choice (как `anketa_builder.py`)
    и label `«Поле:» <курсор>` для freeform.
  - Стили общие: цвета из `style.py`, никаких локальных констант, не
    повторяющих основную палитру.
  - Все примитивы идемпотентны — можно звать несколько раз без побочных
    эффектов друг на друга.
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import quote

from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import _Cell

# Dual-mode импорт style: работает и при `import docx_lib` (sys.path на
# export/), и при `from export import docx_lib` (через package).
try:
    import style as S          # type: ignore[no-redef]
except ModuleNotFoundError:
    from . import style as S

# taxonomy — словарь таксонов (scripts/taxonomy.py).
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    import taxonomy


# ---------------------------------------------------------------------------
# Цвета: RGBColor.from_string ожидает 6-hex без префикса.
# Используем напрямую значения из style.py CATEGORY_COLORS / FLAG_COLORS / …
# ---------------------------------------------------------------------------

PRIMARY = "1a3a5c"
TEXT = "1f2937"
TEXT_MUTED = "5b6b7e"
TEXT_DIM = "6b7280"
WARNING_LABEL = "7a5c00"
ZEBRA = "f4f6f9"


# ---------------------------------------------------------------------------
# Глобальный счётчик ID для bookmark'ов (Word требует уникальный w:id).
# Стартуем с большого числа, чтобы не конфликтовать со скрытыми bookmark'ами,
# которые могут создаваться самим python-docx.
# ---------------------------------------------------------------------------

_BOOKMARK_ID = [10_000]


def next_bookmark_id() -> int:
    """Выдать уникальный id для bookmark."""
    _BOOKMARK_ID[0] += 1
    return _BOOKMARK_ID[0]


def reset_bookmark_id(start: int = 10_000) -> None:
    """Сбросить счётчик (нужно в тестах для воспроизводимости)."""
    _BOOKMARK_ID[0] = start


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def region_anchor(name: str) -> str:
    """Slug для bookmark региона: `region_сием_рип_и_ангкор`.

    Используется как в `add_region_header` (создание якоря), так и в
    `add_internal_link` из coverage-таблицы (целевой anchor).
    """
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return f"region_{s}"


def poi_anchor(num: int) -> str:
    """Slug для bookmark POI карточки: `poi_42`."""
    return f"poi_{num}"


def cluster_anchor(name: str) -> str:
    """Slug для bookmark cluster заголовка: `cluster_водопады_плато_боловен`."""
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return f"cluster_{s}"


# ---------------------------------------------------------------------------
# Low-level XML helpers
# ---------------------------------------------------------------------------

def set_cell_bg(cell: _Cell, hex_color: str) -> None:
    """Залить ячейку фоном (6-hex без #)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_cell_border(
    cell: _Cell, *,
    left_size: int = 0, left_color: str = "auto",
    right_size: int = 0, right_color: str = "auto",
    top_size: int = 0, top_color: str = "auto",
    bottom_size: int = 0, bottom_color: str = "auto",
) -> None:
    """Установить границы ячейки. size в 1/8 pt (8 = 1pt, 32 = 4pt)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for side, sz, color in [
        ("left", left_size, left_color),
        ("right", right_size, right_color),
        ("top", top_size, top_color),
        ("bottom", bottom_size, bottom_color),
    ]:
        if sz:
            b = OxmlElement(f"w:{side}")
            b.set(qn("w:val"), "single")
            b.set(qn("w:sz"), str(sz))
            b.set(qn("w:color"), color)
            tc_borders.append(b)
    tc_pr.append(tc_borders)


def add_bookmark(paragraph, name: str, bookmark_id: int | None = None) -> int:
    """Добавить внутренний bookmark в начало параграфа.

    Возвращает использованный id (для возможного `bookmarkEnd` снаружи,
    хотя мы делаем оба элемента в одной операции).
    """
    bid = bookmark_id if bookmark_id is not None else next_bookmark_id()
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bid))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bid))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)
    return bid


def _make_hyperlink_run_props(
    *, color: str, bold: bool, size_pt: float,
) -> OxmlElement:
    """`w:rPr` для текста-ссылки с native Hyperlink style (нужно Pages,
    Google Docs и некоторым другим клиентам — не только цвет/underline)."""
    r_pr = OxmlElement("w:rPr")
    # Hyperlink — standard built-in Word style. Без него Pages трактует
    # `<w:hyperlink>` как обычный run и не показывает кликабельность.
    style_ref = OxmlElement("w:rStyle")
    style_ref.set(qn("w:val"), "Hyperlink")
    r_pr.append(style_ref)
    c = OxmlElement("w:color"); c.set(qn("w:val"), color); r_pr.append(c)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); r_pr.append(u)
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), str(int(size_pt * 2)))
    r_pr.append(sz)
    if bold:
        r_pr.append(OxmlElement("w:b"))
    return r_pr


def _ensure_hyperlink_style(doc) -> None:
    """Гарантировать что в styles.xml есть запись `Hyperlink` (Word
    обычно создаёт её при первой вставке link через UI, но python-docx
    стартует с пустого набора — мы добавим вручную если нет)."""
    styles_part = doc.part.styles
    styles_el = styles_part.element
    for s in styles_el.findall(qn("w:style")):
        if s.get(qn("w:styleId")) == "Hyperlink":
            return
    style = OxmlElement("w:style")
    style.set(qn("w:type"), "character")
    style.set(qn("w:styleId"), "Hyperlink")
    name = OxmlElement("w:name"); name.set(qn("w:val"), "Hyperlink"); style.append(name)
    basedOn = OxmlElement("w:basedOn"); basedOn.set(qn("w:val"), "DefaultParagraphFont"); style.append(basedOn)
    uiPriority = OxmlElement("w:uiPriority"); uiPriority.set(qn("w:val"), "99"); style.append(uiPriority)
    style.append(OxmlElement("w:unhideWhenUsed"))
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color"); color.set(qn("w:val"), "0563C1"); color.set(qn("w:themeColor"), "hyperlink"); rPr.append(color)
    u = OxmlElement("w:u"); u.set(qn("w:val"), "single"); rPr.append(u)
    style.append(rPr)
    styles_el.append(style)


def add_internal_link(
    paragraph, anchor: str, text: str, *,
    color: str = PRIMARY, bold: bool = False, size_pt: float = 11,
) -> None:
    """Вставить внутренний hyperlink на bookmark (`w:hyperlink w:anchor=…`).

    Pages не поддерживает `w:anchor` навигацию — ссылки видны, но не
    кликабельны. Word / Google Docs / LibreOffice / iOS Word app — OK.
    """
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("w:anchor"), anchor)
    new_run = OxmlElement("w:r")
    new_run.append(_make_hyperlink_run_props(
        color=color, bold=bold, size_pt=size_pt))
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def add_external_hyperlink(
    paragraph, url: str, text: str, *,
    color: str = PRIMARY, bold: bool = False, size_pt: float = 11,
) -> None:
    """Вставить внешний hyperlink (http://…) — для ссылок на источники и
    Google Images. Использует Hyperlink style → корректно работает в
    Pages / Word / Google Docs / iOS Word."""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    new_run.append(_make_hyperlink_run_props(
        color=color, bold=bold, size_pt=size_pt))
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def add_run(
    paragraph, text: str, *,
    bold: bool = False, italic: bool = False,
    color: str | None = None, size_pt: float | None = None,
    font: str | None = None,
) -> None:
    """Добавить run с форматированием."""
    run = paragraph.add_run(text)
    if bold:
        run.bold = True
    if italic:
        run.italic = True
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    if size_pt:
        run.font.size = Pt(size_pt)
    if font:
        run.font.name = font


def set_para_spacing(paragraph, before_pt: float = 0, after_pt: float = 0) -> None:
    """Удобный helper для интервалов до/после параграфа."""
    pf = paragraph.paragraph_format
    pf.space_before = Pt(before_pt)
    pf.space_after = Pt(after_pt)


def set_paragraph_keep(paragraph, *, with_next: bool = True,
                       lines_together: bool = True) -> None:
    """Расставить `w:keepNext` и/или `w:keepLines` на параграфе.

    `keepNext` — Word/Pages держит этот параграф вместе со следующим.
    `keepLines` — не разбивать строки параграфа между страницами.
    Применяется на все non-last параграфы внутри POI карточки чтобы
    избежать разрыва на странице.
    """
    p_pr = paragraph._p.get_or_add_pPr()
    if with_next:
        kn = OxmlElement("w:keepNext")
        p_pr.append(kn)
    if lines_together:
        kl = OxmlElement("w:keepLines")
        p_pr.append(kl)


def set_table_cant_split(tbl) -> None:
    """Запретить разрыв строк таблицы между страницами (`w:cantSplit`).

    Применяется ко всем строкам таблицы — Word/Pages держат содержимое
    строки на одной странице. Используется для POI-карточек, чтобы
    карточка не обрывалась хвостом на новой странице.
    """
    for row in tbl.rows:
        tr_pr = row._tr.get_or_add_trPr()
        cant_split = OxmlElement("w:cantSplit")
        tr_pr.append(cant_split)


def add_horizontal_rule_in_cell(cell: _Cell, color: str = "d0d6dd") -> None:
    """Тонкая разделительная линия внутри ячейки таблицы."""
    p = cell.add_paragraph()
    set_para_spacing(p, 2, 0)
    p_pr = p._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "4")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


# ---------------------------------------------------------------------------
# Колорные helpers
# ---------------------------------------------------------------------------

def lighten_hex(hex_color: str, factor: float) -> str:
    """Осветлить hex-цвет (0.0 — без изменений, 1.0 — белый).

    Принимает hex с/без префикса `#`, возвращает 6-hex без `#`.
    """
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    r = round(r + (255 - r) * factor)
    g = round(g + (255 - g) * factor)
    b = round(b + (255 - b) * factor)
    return f"{r:02x}{g:02x}{b:02x}"


def google_images_url(name: str) -> str:
    """URL поиска картинок Google Images по названию (percent-encoded)."""
    return f"https://www.google.com/search?tbm=isch&q={quote(name)}"


# ---------------------------------------------------------------------------
# Anketa-style примитивы (соответствует подходу `anketa_builder.py`)
# ---------------------------------------------------------------------------

def add_choice_question(
    doc, *,
    label: str,
    options: list[str],
    selected: list[str] | None = None,
    multi: bool = False,
    label_size_pt: float = 12,
    option_size_pt: float = 12,
    hint: str | None = None,
    indent_cm: float = 0.8,
) -> None:
    """Anketa-style чекбокс-вопрос: label + `[ ]` опции.

    Каждая опция — отдельный параграф с маркером `[ ]` или `[x]` (если
    `val in selected`). Пользователь меняет вручную, без раздражающих
    SDT-плейсхолдеров.
    """
    selected = set(selected or [])
    label_p = doc.add_paragraph()
    set_para_spacing(label_p, 8, 2)
    add_run(label_p, label, bold=True, color="3b4554", size_pt=label_size_pt)
    if hint:
        add_run(label_p, f"  ({hint})",
                italic=True, color=TEXT_DIM, size_pt=label_size_pt - 2)

    for option in options:
        op = doc.add_paragraph()
        op.paragraph_format.left_indent = Cm(indent_cm)
        set_para_spacing(op, 0, 1)
        mark = "[x]" if option in selected else "[ ]"
        is_selected = option in selected
        add_run(op, f"{mark}  ", bold=is_selected,
                color=PRIMARY if is_selected else None,
                size_pt=option_size_pt)
        add_run(op, option, bold=is_selected,
                color=PRIMARY if is_selected else None,
                size_pt=option_size_pt)


def add_text_field(
    doc, *,
    label: str,
    prefill: str = "",
    label_color: str = WARNING_LABEL,
    label_size_pt: float = 12,
    before_pt: float = 6, after_pt: float = 6,
) -> None:
    """Anketa-style текстовое поле: `label: <prefill или пусто>`.

    Курсор оказывается после `:` — пользователь сразу печатает, ничего
    не надо стирать. Если `prefill` непустой, он подставляется (для
    pre-filled DOCX, аналогично UPDATE-режиму anketa).
    """
    p = doc.add_paragraph()
    set_para_spacing(p, before_pt, after_pt)
    add_run(p, f"{label}: ", bold=True, color=label_color, size_pt=label_size_pt)
    if prefill:
        add_run(p, prefill, color=TEXT, size_pt=label_size_pt)


def add_text_field_in_cell(
    cell: _Cell, *,
    label: str,
    prefill: str = "",
    label_color: str = WARNING_LABEL,
    label_size_pt: float = 12,
    before_pt: float = 6, after_pt: float = 6,
) -> None:
    """То же, что `add_text_field`, но внутри ячейки таблицы (для POI cards)."""
    p = cell.add_paragraph()
    set_para_spacing(p, before_pt, after_pt)
    add_run(p, f"{label}: ", bold=True, color=label_color, size_pt=label_size_pt)
    if prefill:
        add_run(p, prefill, color=TEXT, size_pt=label_size_pt)


# ---------------------------------------------------------------------------
# Stage 3 — высокоуровневые блоки
# ---------------------------------------------------------------------------

def add_region_header(
    doc, *,
    name: str,
    poi_count: int,
    mode: str | None = None,          # ignored, kept для backwards compat
    poi_list: list | None = None,     # ignored, kept для backwards compat
    tag_selected: str | None = None,  # ignored — тег выводится в caller
    page_width_cm: float = 17,
) -> None:
    """Section bar региона — синяя плашка с названием и POI-counter.

    Содержит только bar + bookmark. Описание / tag / authors summary —
    отдельные функции, вызываются caller'ом (build_docx) в нужном порядке.
    Параметры `mode`, `poi_list`, `tag_selected` оставлены для обратной
    совместимости вызовов, но игнорируются (режим больше не выводится;
    mini-TOC и tag вынесены).
    """
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = False
    tbl.columns[0].width = Cm(page_width_cm)
    cell = tbl.rows[0].cells[0]
    cell.width = Cm(page_width_cm)
    set_cell_bg(cell, PRIMARY)

    p = cell.paragraphs[0]
    set_para_spacing(p, 4, 4)
    add_bookmark(p, region_anchor(name))
    add_run(p, f"{name}  ·  {poi_count} POI",
            bold=True, color="ffffff", size_pt=14)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def add_cluster_header(
    doc, *,
    name: str,
    member_count: int,
    note: str,
    page_width_cm: float = 17,
) -> None:
    """Заголовок кластера (group of POI): синие верх/низ границы, описание.

    Создаёт bookmark `cluster_<slug>` — на него могут ссылаться cluster-chip
    карточек POI-членов (в будущем).
    """
    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = False
    tbl.columns[0].width = Cm(page_width_cm)
    cell = tbl.rows[0].cells[0]
    cell.width = Cm(page_width_cm)
    set_cell_bg(cell, "eaf0f8")
    set_cell_border(
        cell,
        top_size=8, top_color=S.FLAG_COLORS["cluster"],
        bottom_size=8, bottom_color=S.FLAG_COLORS["cluster"],
    )

    p = cell.paragraphs[0]
    set_para_spacing(p, 4, 0)
    add_bookmark(p, cluster_anchor(name))
    add_run(p, "◆ CLUSTER  ", bold=True,
            color=S.FLAG_COLORS["cluster"], size_pt=11)
    add_run(p, name, bold=True, color="1f3a52", size_pt=11)
    add_run(p, f"   ({member_count} POI)", color=TEXT_DIM, size_pt=10)

    note_p = cell.add_paragraph()
    set_para_spacing(note_p, 0, 4)
    add_run(note_p, note, color=TEXT_MUTED, size_pt=9)


def add_poi_card(
    doc, *,
    num: int,
    name_ru: str,
    name_local: str,
    category: str,
    counts_line: str,
    excerpts: list[dict],
    characteristics: str,
    flags: list[dict] | None = None,
    user_comment: str = "",
    page_width_cm: float = 17,
    search_query: str | None = None,
) -> None:
    """POI-карточка с цветной accent-полосой слева и tinted фоном.

    Структура:
      ┌─[accent]──────────────────────────────────────────┐
      │  #N **Название** (local) →link Google Images   [BADGE]│
      │  HIGH 2 (рек 2 · neg 0) · OUTLIER 1 · …          │
      │  ───────────────────────────                       │
      │  ✓ **Автор** · 2024 · HIGH: «цитата»              │
      │  ✗ ...                                            │
      │  Характеристики: ...                              │
      │  [combined: X] [cluster: Y]                       │
      │  ───────────────────────────                       │
      │  Комментарий:  ← курсор сразу здесь               │
      └───────────────────────────────────────────────────┘

    Параметры:
      - `excerpts`: список dict {tone, author_name, year, similarity, url, text}
      - `flags`:    список dict {kind, label, link_to_poi|link_to_cluster|None}
      - `user_comment`: prefill (если уже есть в md); если "" — поле пустое,
                        пользователь печатает в DOCX.
    """
    accent = S.CATEGORY_COLORS[category]
    tint = lighten_hex(accent, 0.93)

    tbl = doc.add_table(rows=1, cols=1)
    tbl.autofit = False
    tbl.columns[0].width = Cm(page_width_cm)
    cell = tbl.rows[0].cells[0]
    cell.width = Cm(page_width_cm)
    set_cell_bg(cell, tint)
    set_cell_border(cell, left_size=32, left_color=accent)
    set_table_cant_split(tbl)

    # Удаляем дефолтный пустой paragraph в ячейке
    default_p = cell.paragraphs[0]
    default_p._p.getparent().remove(default_p._p)

    # === Header: # + название (link) + badge (nested 1×2 table) ===
    title_col_cm = page_width_cm - 4
    header_tbl = cell.add_table(rows=1, cols=2)
    header_tbl.autofit = False
    header_tbl.columns[0].width = Cm(title_col_cm)
    header_tbl.columns[1].width = Cm(3)
    set_table_cant_split(header_tbl)
    title_cell = header_tbl.rows[0].cells[0]
    title_cell.width = Cm(title_col_cm)
    badge_cell = header_tbl.rows[0].cells[1]
    badge_cell.width = Cm(3)
    set_cell_bg(title_cell, tint)
    set_cell_bg(badge_cell, accent)

    title_p = title_cell.paragraphs[0]
    set_para_spacing(title_p, 0, 0)
    set_paragraph_keep(title_p)
    add_bookmark(title_p, poi_anchor(num))
    add_run(title_p, f"#{num}  ", color=TEXT_DIM, size_pt=12)
    # Название POI — Google Images link. В DOCX ищем по `search_query`
    # (если передан, например «Angkor Wat in Cambodia» для дизамбигуации
    # общих английских терминов) или fallback `name_local`. Используем
    # ASCII-only query: прямой unicode URL ломается в Pages (двойное
    # encode'ит). Кликабельный остаётся русский label.
    query = search_query or name_local
    add_external_hyperlink(
        title_p, google_images_url(query), name_ru,
        color=accent, bold=True, size_pt=13,
    )
    add_run(title_p, f"  ({name_local})", color=TEXT_DIM, size_pt=10)

    badge_p = badge_cell.paragraphs[0]
    set_para_spacing(badge_p, 0, 0)
    badge_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_run(badge_p, S.CATEGORY_SHORT[category],
            bold=True, color="ffffff", size_pt=9)
    badge_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    # === Counts line ===
    counts_p = cell.add_paragraph()
    set_para_spacing(counts_p, 4, 4)
    add_run(counts_p, counts_line, color=TEXT_MUTED, size_pt=9, font="Menlo")

    # === Excerpts ===
    _render_excerpts(cell, excerpts)

    # === Characteristics ===
    if characteristics:
        char_p = cell.add_paragraph()
        set_para_spacing(char_p, 6, 4)
        add_run(char_p, "Характеристики: ", bold=True,
                color="3b4554", size_pt=10)
        add_run(char_p, characteristics, color=TEXT, size_pt=10)

    # === Flag chips ===
    if flags:
        flag_p = cell.add_paragraph()
        set_para_spacing(flag_p, 4, 2)
        for i, fl in enumerate(flags):
            if i > 0:
                add_run(flag_p, "   ", size_pt=9)
            color = S.FLAG_COLORS.get(fl["kind"], "5a6c87")
            label = fl["label"]
            link_to_poi = fl.get("link_to_poi")   # int (POI num) или None
            link_to_cluster = fl.get("link_to_cluster")
            if isinstance(link_to_poi, int):
                add_run(flag_p, "  ", size_pt=9)
                add_internal_link(flag_p, poi_anchor(link_to_poi),
                                  label.upper(),
                                  color=color, bold=True, size_pt=9)
                add_run(flag_p, "  ", size_pt=9)
            elif link_to_cluster:
                add_run(flag_p, "  ", size_pt=9)
                add_internal_link(flag_p, cluster_anchor(link_to_cluster),
                                  label.upper(),
                                  color=color, bold=True, size_pt=9)
                add_run(flag_p, "  ", size_pt=9)
            else:
                add_run(flag_p, f"  {label.upper()}  ",
                        bold=True, color=color, size_pt=9)

    # === User comment field (всегда видно, ВСЕГДА editable в DOCX) ===
    add_horizontal_rule_in_cell(cell, color="d4a843")
    add_text_field_in_cell(
        cell,
        label="Комментарий",
        prefill=user_comment,
        label_color=WARNING_LABEL,
        label_size_pt=12,
        before_pt=6, after_pt=6,
    )

    # Anti-page-break: расставляем keepNext+keepLines на ВСЕХ параграфах
    # внутри cell, кроме последнего. Word и Pages честно держат цепочку
    # `keepNext`-параграфов на одной странице (надёжнее чем cantSplit
    # на outer row при больших карточках). Последний параграф без
    # keepNext позволяет page-break MOVE'нуть всю карточку на следующую
    # страницу, если не помещается.
    paragraphs_in_cell = cell.paragraphs
    for p in paragraphs_in_cell[:-1]:
        set_paragraph_keep(p, with_next=True, lines_together=True)
    if paragraphs_in_cell:
        set_paragraph_keep(paragraphs_in_cell[-1],
                           with_next=False, lines_together=True)


def _render_excerpts(cell: _Cell, excerpts: list[dict]) -> None:
    """Рендер выдержек в POI-карточке.

    Формат: `<tone> Имя («Название отчёта») · year · TIER: цитата`,
    где «Название отчёта» — кликабельная ссылка на URL.

    Если title нет, но url есть — link навешивается на имя автора
    (fallback). Если url нет — просто имя без link.
    """
    tone_glyphs = {"pos": "✓", "neg": "✗", "neu": "•"}
    for ex in excerpts:
        ex_p = cell.add_paragraph()
        pf = ex_p.paragraph_format
        pf.left_indent = Cm(0.4)
        pf.first_line_indent = Cm(-0.4)
        set_para_spacing(ex_p, 2, 2)

        tone = ex.get("tone", "neu")
        add_run(ex_p, tone_glyphs.get(tone, "·") + " ",
                bold=True, color=S.TONE_COLORS.get(tone, "6b7280"), size_pt=11)

        author = ex.get("author_name", "?")
        url = ex.get("url")
        title = ex.get("report_title")

        # Имя автора — plain bold accent (надёжно в Pages)
        add_run(ex_p, author, bold=True, color=PRIMARY, size_pt=10)
        # Кликабельный chip-«Название отчёта» — только в карточках
        if title and url:
            add_run(ex_p, " (", color=TEXT_DIM, size_pt=10)
            add_external_hyperlink(
                ex_p, url, f"«{title}»",
                color=PRIMARY, bold=False, size_pt=10,
            )
            add_run(ex_p, ")", color=TEXT_DIM, size_pt=10)
        elif url and not title:
            # Fallback: нет title — link на имени отдельным chip-domain
            add_run(ex_p, " ", color=TEXT_DIM, size_pt=10)
            add_external_hyperlink(
                ex_p, url, f"({_shorten_url_for_display(url)})",
                color=PRIMARY, bold=False, size_pt=10,
            )

        if ex.get("year"):
            add_run(ex_p, f" · {ex['year']}", color=TEXT_DIM, size_pt=10)
        sim = ex.get("similarity")
        if sim:
            add_run(ex_p, " · ", color="9aa3ad", size_pt=10)
            add_run(ex_p, sim, bold=True,
                    color=S.SIMILARITY_COLORS.get(sim, "6b7280"), size_pt=9)

        text = ex.get("text", "")
        add_run(ex_p, f": {text}", color=TEXT, size_pt=10)


def _shorten_url_for_display(url: str) -> str:
    """`https://aleksblog.com/angkor/` → `aleksblog.com`."""
    from urllib.parse import urlparse
    try:
        netloc = urlparse(url).netloc
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or url
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Coverage table (используется на cover Stage 3)
# ---------------------------------------------------------------------------

def add_coverage_table(
    doc, *,
    rows: list[tuple[str, int, int, int, int, int, int, int]],
    totals: tuple[int, int, int, int, int, int, int],
    primary_color: str = PRIMARY,
) -> None:
    """Coverage-таблица по регионам × категории.

    rows:   список (region_name, poi_total, strong, weak, hidden, contested,
                    red_flag, low_signal); regions с приставкой
                    «Кластер — ...» рендерятся приглушённым шрифтом и БЕЗ
                    кликабельной ссылки на region anchor.
    totals: (poi_total, strong, weak, hidden, contested, red_flag, low_signal).

    Первая колонка названия региона — кликабельный internal link на
    `region_<slug>` (исключение — cluster sub-rows).
    """
    # Бейдж-ярлыки категорий — русские (taxonomy), в каноническом порядке
    # колонок STRONG/WEAK/HIDDEN/CONTESTED/RED/LOW.
    _badge_keys = ["STRONG_CONFIRMED", "WEAK_CONFIRMED", "HIDDEN_GEM",
                   "CONTESTED", "RED_FLAG", "LOW_SIGNAL"]
    header = ["Регион", "POI"] + [
        taxonomy.label("poi_category_badge", k) for k in _badge_keys]
    # Русские бейджи шире EN-аббревиатур → колонки категорий уширены.
    col_widths = [4.4, 1.0, 1.9, 1.8, 2.1, 1.9, 1.9, 1.7]

    cov_tbl = doc.add_table(rows=len(rows) + 2, cols=len(header))
    cov_tbl.autofit = False
    for i, w in enumerate(col_widths):
        for r in cov_tbl.rows:
            r.cells[i].width = Cm(w)

    cat_cols = {
        2: "STRONG CONFIRMED", 3: "WEAK CONFIRMED",
        4: "HIDDEN GEM", 5: "CONTESTED",
        6: "RED FLAG", 7: "LOW SIGNAL",
    }
    for i, h in enumerate(header):
        c = cov_tbl.rows[0].cells[i]
        if i in cat_cols:
            set_cell_bg(c, S.CATEGORY_COLORS[cat_cols[i]])
        else:
            set_cell_bg(c, primary_color)
        p = c.paragraphs[0]
        set_para_spacing(p, 2, 2)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_run(p, h, bold=True, color="ffffff", size_pt=9)

    for ri, (region, total, s, w, h, cnt, r, low) in enumerate(rows, 1):
        row = cov_tbl.rows[ri]
        is_cluster = region.lower().startswith("кластер")
        vals = [
            region, str(total),
            str(s) if s else "·", str(w) if w else "·",
            str(h) if h else "·", str(cnt) if cnt else "·",
            str(r) if r else "·", str(low) if low else "·",
        ]
        for ci, val in enumerate(vals):
            c = row.cells[ci]
            if ri % 2 == 0:
                set_cell_bg(c, ZEBRA)
            p = c.paragraphs[0]
            set_para_spacing(p, 2, 2)
            if ci > 0:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            if ci == 0 and not is_cluster:
                add_internal_link(p, region_anchor(region), val,
                                  color=primary_color, size_pt=9)
            else:
                color = TEXT_DIM if is_cluster else TEXT
                add_run(p, val, italic=is_cluster, color=color, size_pt=9)

    total_row = cov_tbl.rows[-1]
    pt, ps, pw, ph, pc, pr, plow = totals
    total_vals = ["ВСЕГО", str(pt), str(ps), str(pw),
                  str(ph), str(pc), str(pr), str(plow)]
    for ci, val in enumerate(total_vals):
        c = total_row.cells[ci]
        set_cell_bg(c, "eaf0f8")
        p = c.paragraphs[0]
        set_para_spacing(p, 2, 2)
        if ci > 0:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_run(p, val, bold=True, color=primary_color, size_pt=9)


def add_category_distribution(
    doc, *,
    distribution: list[tuple[str, int]],
    column_widths_cm: float = 2.8,
) -> None:
    """6 цветных плашек распределения по категориям (cover-блок).

    distribution: [(category, count), ...] — например
    `[("STRONG CONFIRMED", 0), ..., ("LOW SIGNAL", 28)]`. Порядок и
    состав определяет вызывающий.
    """
    dist_tbl = doc.add_table(rows=2, cols=len(distribution))
    dist_tbl.autofit = False
    for i, (cat, cnt) in enumerate(distribution):
        c0 = dist_tbl.rows[0].cells[i]
        c1 = dist_tbl.rows[1].cells[i]
        c0.width = Cm(column_widths_cm); c1.width = Cm(column_widths_cm)
        color = S.CATEGORY_COLORS[cat]
        tint = lighten_hex(color, 0.90)
        set_cell_bg(c0, tint); set_cell_bg(c1, tint)
        set_cell_border(c0, top_size=16, top_color=color)
        p0 = c0.paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p0, 6, 0)
        add_run(p0, str(cnt), bold=True, color=color, size_pt=18)
        p1 = c1.paragraphs[0]
        p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_para_spacing(p1, 0, 6)
        add_run(p1, S.CATEGORY_SHORT[cat], bold=True,
                color=color, size_pt=8)


def add_key_params_table(
    doc, *,
    rows: list[tuple[str, str]],
    label_col_cm: float = 4,
    value_col_cm: float = 13,
    primary_color: str = PRIMARY,
) -> None:
    """Параметры поездки на cover: zebra-таблица label/value."""
    tbl = doc.add_table(rows=len(rows), cols=2)
    tbl.autofit = False
    tbl.columns[0].width = Cm(label_col_cm)
    tbl.columns[1].width = Cm(value_col_cm)
    for i, (k, v) in enumerate(rows):
        c0, c1 = tbl.rows[i].cells
        c0.width = Cm(label_col_cm); c1.width = Cm(value_col_cm)
        if i % 2 == 0:
            set_cell_bg(c0, ZEBRA); set_cell_bg(c1, ZEBRA)
        p0 = c0.paragraphs[0]
        set_para_spacing(p0, 2, 2)
        add_run(p0, k, bold=True, color=primary_color, size_pt=10)
        p1 = c1.paragraphs[0]
        set_para_spacing(p1, 2, 2)
        add_run(p1, v, color=TEXT, size_pt=10)

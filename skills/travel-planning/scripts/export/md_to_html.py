"""md_to_html.py — минимальный markdown → HTML конвертер.

Поддерживает то, что реально встречается в stage-артефактах
travel-planning:

  - заголовки  `## foo` / `### foo` / `#### foo`
  - bold       `**foo**`
  - italic     `*foo*` / `_foo_`
  - inline code `` `foo` ``
  - ссылки     `[text](url)`
  - bullet-list  `- item` (одноуровневый + вложенный двухуровневый через 2/4 пробела)
  - checkbox-list `- [ ] item` / `- [x] item`
  - таблицы GFM `| a | b |\\n|---|---|\\n| 1 | 2 |`
  - параграфы  (пустая строка = разделитель)
  - горизонталь `---`

Не поддерживает (и не нужно):
  - блочный код (``` ... ```) — в stage5 не используется
  - blockquote
  - изображения
  - сноски

Stdlib only. Без зависимостей.

TODO-маркеры (`TODO: ...`, `**TODO:**`, `<TODO ...>`) **не** обрабатываются
здесь — это задача renderer'а конкретной стадии (он оборачивает их в
`<span class="todo">` для подсветки).
"""
from __future__ import annotations

import html
import re


def md_to_html(text: str) -> str:
    """Конвертировать markdown-фрагмент в HTML.

    Принимает body одной секции (без YAML frontmatter, без H1). Возвращает
    HTML без обёртки `<html><body>` — это inline-фрагмент.
    """
    if not text or not text.strip():
        return ""
    blocks = _split_blocks(text)
    out_parts: list[str] = []
    for block in blocks:
        rendered = _render_block(block)
        if rendered:
            out_parts.append(rendered)
    return "\n".join(out_parts)


# ---------------------------------------------------------------------------
# Разбиение на блоки
# ---------------------------------------------------------------------------


def _split_blocks(text: str) -> list[list[str]]:
    """Разбить текст на блоки по пустым строкам, сохраняя строки внутри."""
    lines = text.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


# ---------------------------------------------------------------------------
# Рендер одного блока
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_HR_RE = re.compile(r"^-{3,}\s*$")
_TABLE_DELIM_RE = re.compile(r"^\s*\|?\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?\s*$")
_LIST_BULLET_RE = re.compile(r"^(\s*)-\s+(.*)$")
_CHECKBOX_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")


def _render_block(lines: list[str]) -> str:
    """Распознать тип блока и отрендерить."""
    if not lines:
        return ""

    # Заголовок (один-строчный блок).
    if len(lines) == 1:
        m = _HEADING_RE.match(lines[0])
        if m:
            level = len(m.group(1))
            content = _render_inline(m.group(2).strip())
            return f"<h{level}>{content}</h{level}>"
        if _HR_RE.match(lines[0]):
            return "<hr>"

    # Таблица: первая строка с `|`, вторая — разделитель `---`.
    if len(lines) >= 2 and "|" in lines[0] and _TABLE_DELIM_RE.match(lines[1]):
        return _render_table(lines)

    # Список (все строки начинаются с `- ` или продолжают список).
    if all(_LIST_BULLET_RE.match(ln) or ln.startswith(" ") for ln in lines):
        if any(_LIST_BULLET_RE.match(ln) for ln in lines):
            return _render_list(lines)

    # Параграф.
    text = " ".join(ln.strip() for ln in lines)
    return f"<p>{_render_inline(text)}</p>"


# ---------------------------------------------------------------------------
# Inline-разметка
# ---------------------------------------------------------------------------

# Inline-преобразования делаем в фиксированном порядке. Порядок важен:
# bold/italic ДО inline-code конфликтуют с `*` внутри code; делаем code
# первым, потом links, потом bold, потом italic.

_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)")
_UNDERSCORE_ITALIC_RE = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")


def _render_inline(text: str) -> str:
    """Применить inline-разметку к одной строке/параграфу.

    Алгоритм:
      1. escape всего текста.
      2. достать inline-code → placeholder (чтобы * внутри code не
         триггерил bold/italic).
      3. рендер ссылок, bold, italic.
      4. восстановить inline-code.
    """
    # Шаг 1: escape.
    escaped = html.escape(text, quote=False)

    # Шаг 2: вынуть код в placeholder'ы.
    code_blocks: list[str] = []
    def _stash_code(m: re.Match) -> str:
        code_blocks.append(html.escape(m.group(1), quote=False))
        return f"\x00CODE{len(code_blocks) - 1}\x00"

    # Внимание: inline-code мы должны вытаскивать ДО escape, чтобы внутри
    # код не превратился в `&amp;` и сравнения не сломались. Делаем
    # двумя проходами: на оригинале вынимаем кодовые куски и плейсхолдим,
    # потом escape, потом подставляем уже escape'нутые куски.
    raw = text
    raw_with_placeholders = _INLINE_CODE_RE.sub(_stash_code, raw)
    escaped = html.escape(raw_with_placeholders, quote=False)

    # Шаг 3: ссылки → bold → italic.
    escaped = _LINK_RE.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    escaped = _UNDERSCORE_ITALIC_RE.sub(r"<em>\1</em>", escaped)

    # Шаг 4: восстановить inline-code (внутри кода уже escape'нуто).
    def _restore_code(m: re.Match) -> str:
        idx = int(m.group(1))
        return f"<code>{code_blocks[idx]}</code>"

    escaped = re.sub(r"\x00CODE(\d+)\x00", _restore_code, escaped)
    return escaped


# ---------------------------------------------------------------------------
# Таблицы
# ---------------------------------------------------------------------------


def _render_table(lines: list[str]) -> str:
    """Отрендерить GFM-таблицу.

    Поддерживает выравнивание в delimiter-строке (`:---`, `:---:`, `---:`),
    но в большинстве stage-таблиц оно не задано — тогда дефолт left.
    """
    header_cells = _split_table_row(lines[0])
    delim_cells = _split_table_row(lines[1])
    aligns = [_align_from_delim(c) for c in delim_cells]
    body_rows = [_split_table_row(ln) for ln in lines[2:] if "|" in ln]

    out = ['<table class="data-table">', "<thead><tr>"]
    for cell, align in zip(header_cells, aligns):
        style = f' style="text-align: {align}"' if align != "left" else ""
        out.append(f"<th{style}>{_render_inline(cell)}</th>")
    out.append("</tr></thead>")

    out.append("<tbody>")
    for row in body_rows:
        out.append("<tr>")
        # Если строка короче header'а — добиваем пустыми ячейками.
        padded = list(row) + [""] * (len(header_cells) - len(row))
        for cell, align in zip(padded, aligns):
            style = f' style="text-align: {align}"' if align != "left" else ""
            out.append(f"<td{style}>{_render_inline(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def _split_table_row(line: str) -> list[str]:
    """Разбить строку таблицы на ячейки по `|`, обрезав крайние."""
    parts = line.split("|")
    # Срезать пустые крайние, если есть лидирующий/трейлинг `|`.
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.strip() for p in parts]


def _align_from_delim(delim: str) -> str:
    delim = delim.strip()
    left = delim.startswith(":")
    right = delim.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    return "left"


# ---------------------------------------------------------------------------
# Списки (с вложенностью один уровень + checkbox)
# ---------------------------------------------------------------------------


def _render_list(lines: list[str]) -> str:
    """Отрендерить bullet-list. Поддерживает 1 уровень вложенности.

    Каждая строка либо `- ...`, либо продолжение элемента (отступ).
    Продолжения присоединяются к последнему элементу. Если внутри
    списка встречается checkbox `- [ ] ...` — добавляем CSS-класс.
    """
    items: list[tuple[int, str, bool, bool | None]] = []
    # (depth, content, is_checkbox, checked_state)
    base_indent = None

    for line in lines:
        m = _LIST_BULLET_RE.match(line)
        if m:
            indent_str, content = m.group(1), m.group(2)
            indent = len(indent_str)
            if base_indent is None:
                base_indent = indent
            depth = 0 if indent <= base_indent else 1
            cb = _CHECKBOX_RE.match(content)
            if cb:
                checked = cb.group(1).lower() == "x"
                items.append((depth, cb.group(2), True, checked))
            else:
                items.append((depth, content, False, None))
        else:
            # Продолжение последнего элемента.
            if items:
                d, c, ic, ch = items[-1]
                items[-1] = (d, c + " " + line.strip(), ic, ch)

    # Собрать HTML.
    out: list[str] = ["<ul>"]
    open_sub = False
    for depth, content, is_cb, checked in items:
        if depth == 0:
            if open_sub:
                out.append("</ul></li>")
                open_sub = False
            li = _format_list_item(content, is_cb, checked)
            out.append(li)
        else:  # depth == 1
            if not open_sub:
                # Закрыть предыдущий <li> и открыть вложенный <ul> внутри него.
                # Простейший вариант — последний </li> заменить на <ul>...
                if out[-1].endswith("</li>"):
                    out[-1] = out[-1][: -len("</li>")]
                out.append("<ul>")
                open_sub = True
            out.append(_format_list_item(content, is_cb, checked))
    if open_sub:
        out.append("</ul></li>")
    out.append("</ul>")
    return "\n".join(out)


def _format_list_item(content: str, is_checkbox: bool, checked: bool | None) -> str:
    """Сформировать один `<li>` элемент."""
    rendered = _render_inline(content)
    if is_checkbox:
        mark = "☑" if checked else "☐"
        cls = "checkbox checked" if checked else "checkbox"
        return f'<li class="{cls}"><span class="cb-mark">{mark}</span> {rendered}</li>'
    return f"<li>{rendered}</li>"

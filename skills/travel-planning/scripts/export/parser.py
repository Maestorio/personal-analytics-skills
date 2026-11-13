"""parser.py — generic md+YAML splitter для файлов стадий.

**Контракт формата** артефактов стадий (секции, YAML-шапка, маркеры) — каноны
`references/stageN/stageN-output-spec.md`; согласованность копий с ними проверяет
`tests/test_format_contract.py`.

Разбирает markdown-файлы стадий (0_scope.md, 3_poi_aggregation.md,
5_final_plan_v1.md, ...) в структуру:

    {
      "frontmatter":          dict,      # распарсенный YAML
      "frontmatter_raw":      str,       # сырой YAML-текст между --- разделителями
      "frontmatter_warnings": list[str], # предупреждения минимального YAML-loader'а
      "body":                 str,       # полный markdown-body после frontmatter
      "title":                str | None,# первый H1
      "sections":             list[dict],# иерархия секций
      "trip_id":              str | None,
      "stage":                str | None,
    }

Секции возвращаются плоским списком top-level (H2) блоков; у каждого
есть свой `subsections` со всеми H3+ детьми. Этого достаточно для
адаптеров под получателя, которые работают в терминах именованных ##-секций
(например, «выкинуть «План реагирования на риски»»).

Engine-уровень держит парсинг секций структурным — он НЕ интерпретирует
stage-специфичную разметку (POI-карточки, day-блоки, транспортные таблицы).
Это — задача stage-модулей, которые добавятся в Steps 2+.

Также экспортируется `parse_md_paste(text)` — fallback для DOCX round-trip
когда пользователь вставляет markdown-текст вместо загрузки заполненного
DOCX. `parse_docx_for_import` — пока заглушка (реальная реализация — в Step 3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# YAML frontmatter
# ---------------------------------------------------------------------------

# Разделитель YAML-блока — строка из ровно трёх дефисов (см. storage-and-naming §5).
_YAML_DELIM = re.compile(r"^---\s*$", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Разделить `text` на (yaml_block, body).

    Frontmatter должен начинаться с `---\\n` и закрываться строкой только
    из `---`. Если валидного frontmatter не нашлось — возвращает ("", text).
    """
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return "", text
    rest = text[4:] if text.startswith("---\n") else text[5:]
    m = _YAML_DELIM.search(rest)
    if not m:
        return "", text
    yaml_block = rest[: m.start()]
    body = rest[m.end():]
    # Срезаем один лидирующий \n у body, если он есть.
    if body.startswith("\n"):
        body = body[1:]
    return yaml_block, body


def _strip_inline_comment(value: str) -> str:
    """Срезать inline `# комментарий` со скаляра, уважая кавычки."""
    in_quote = None
    for i, ch in enumerate(value):
        if in_quote:
            if ch == in_quote and value[i - 1] != "\\":
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            continue
        if ch == "#" and (i == 0 or value[i - 1].isspace()):
            return value[:i].rstrip()
    return value.rstrip()


_SCALAR_TRUE = {"true", "True", "yes", "Yes"}
_SCALAR_FALSE = {"false", "False", "no", "No"}
_SCALAR_NULL = {"null", "Null", "~", ""}


def _split_flow_commas(inner: str) -> list[str]:
    """Разбить содержимое flow-коллекции по запятым верхнего уровня
    (вне вложенных `[]`/`{}` и вне кавычек)."""
    parts: list[str] = []
    depth = 0
    quote = None
    buf: list[str] = []
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_flow_seq(value: str) -> list:
    """Flow-список `[a, b, c]` → список скаляров. Пустой `[]` → `[]`.

    Массовый дрейф в свежих артефактах (`weights_used`, `trip_wishes`,
    `must_have_resolved`, `mcp_extensions_used`…): раньше значение молча
    оставалось строкой `"[a, b]"` → `json.dumps` в интерактивном Stage 2
    сериализовал её посимвольно."""
    inner = value.strip()[1:-1].strip()
    if not inner:
        return []
    return [_parse_scalar(p) for p in _split_flow_commas(inner)]


def _parse_scalar(value: str) -> Any:
    """Распарсить YAML-скаляр — string / int / float / bool / null / flow-list."""
    value = _strip_inline_comment(value).strip()
    if value in _SCALAR_NULL:
        return None
    if value in _SCALAR_TRUE:
        return True
    if value in _SCALAR_FALSE:
        return False
    # Flow-список `[a, b, c]` (пустой `[]` → `[]`).
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        return _parse_flow_seq(value)
    # Строка в кавычках.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    # Целое.
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    # Float.
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            pass
    return value


_FLOW_MAP_RE = re.compile(r"^\{(.*)\}$")


def _parse_flow_mapping(value: str) -> dict | None:
    """Распарсить `{key: val, key: val}` flow-mapping внутри block-списка.

    Возвращает None, если это не flow-mapping или парсинг не удался —
    в этом случае caller трактует значение как обычную строку.
    """
    m = _FLOW_MAP_RE.match(value.strip())
    if not m:
        return None
    inner = m.group(1)
    out: dict = {}
    for part in _split_flow_commas(inner):
        if ":" not in part:
            return None
        k, _, v = part.partition(":")
        out[k.strip()] = _parse_scalar(v)
    return out


def parse_yaml(text: str) -> tuple[dict, list[str]]:
    """Минимальный YAML-loader.

    Поддерживает:
      - плоские `key: value` скаляры (string / int / float / bool / null)
      - block-списки под ключом: `key:\\n  - item\\n  - item`
      - flow-mappings внутри block-списков: `- {name: foo, nights: 3}`
      - вложенные mapping-блоки через отступ: `key:\\n  sub: val\\n  sub2: val`
      - строки в кавычках, `# комментарии`

    Возвращает (parsed_dict, warnings). Непарсимые строки идут в warnings,
    но никогда не падают исключением — engine обязан быть устойчивым
    к schema evolution (см. export-design.md §6).
    """
    out: dict = {}
    warnings: list[str] = []
    lines = text.splitlines()

    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        # Пустые строки и строки-комментарии пропускаем.
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if _indent(line) != 0:
            warnings.append(f"unexpected indent at line {i + 1}: {raw!r}")
            i += 1
            continue

        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            warnings.append(f"unparseable top-level line {i + 1}: {raw!r}")
            i += 1
            continue
        key, value = m.group(1), m.group(2)

        # Inline-комментарий после block-ключа (`longlist:  # 8 регионов…`) не
        # должен превращать ключ в скаляр: сначала срезаем комментарий, потом
        # решаем block-vs-scalar. Иначе block-список молча станет None →
        # секция (регионы) пропадает из экспорта.
        val_nc = _strip_inline_comment(value).strip()

        # Block-скаляр `key: |` / `key: >` (+chomping `-`/`+`/цифра). Полноценный
        # YAML block-scalar не реализуем, но значение не теряем и не выдаём «|»:
        # собираем последующий отступленный блок как строку + warning.
        if re.fullmatch(r"[|>][+-]?\d*", val_nc):
            j = i + 1
            block: list[str] = []
            while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > 0):
                block.append(lines[j].strip())
                j += 1
            warnings.append(
                f"block scalar {val_nc!r} at line {i + 1} не поддержан; "
                f"собран как строка")
            out[key] = "\n".join(block).strip()
            i = j
            continue

        if val_nc == "":
            # Блок: либо список, либо вложенный mapping (peek следующей строки).
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                out[key] = None
                i = j
                continue
            peek = lines[j]
            peek_indent = _indent(peek)
            if peek_indent == 0:
                # Flush-список: элементы `- ` на отступе ключа (валидный YAML;
                # живой кейс Китай stage 0 — блок молча терялся как None).
                if peek.lstrip().startswith("- "):
                    flush: list[str] = []
                    while (j < len(lines) and lines[j].strip()
                           and _indent(lines[j]) == 0
                           and lines[j].lstrip().startswith("- ")):
                        flush.append(lines[j])
                        j += 1
                    out[key] = _parse_block_list(flush, 0, warnings)
                    i = j
                    continue
                out[key] = None
                i = j
                continue
            # Собираем все дочерние строки на этом отступе или глубже.
            child_lines: list[str] = []
            while j < len(lines):
                if not lines[j].strip():
                    child_lines.append("")
                    j += 1
                    continue
                if _indent(lines[j]) < peek_indent:
                    break
                child_lines.append(lines[j])
                j += 1
            # Тип определяем по первому непустому child: `- ` → список, иначе mapping.
            first_real = next((c for c in child_lines if c.strip()), "")
            if first_real.lstrip().startswith("- "):
                out[key] = _parse_block_list(child_lines, peek_indent, warnings)
            else:
                sub, sub_warn = _parse_block_mapping(child_lines, peek_indent)
                warnings.extend(sub_warn)
                out[key] = sub
            i = j
        else:
            out[key] = _parse_scalar(value)
            i += 1
    return out, warnings


def _parse_block_list(child_lines: list[str], base_indent: int, warnings: list[str]) -> list:
    """Распарсить block-список на заданном отступе."""
    items: list = []
    i = 0
    while i < len(child_lines):
        line = child_lines[i]
        if not line.strip():
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent != base_indent:
            warnings.append(f"unexpected list indent: {line!r}")
            i += 1
            continue
        stripped = line.lstrip(" ")
        if not stripped.startswith("- "):
            warnings.append(f"non-list line in list block: {line!r}")
            i += 1
            continue
        rest = stripped[2:]
        # Flow-mapping?
        flow = _parse_flow_mapping(rest)
        if flow is not None:
            items.append(flow)
            i += 1
            continue
        # Inline-скаляр.
        # Цитированная строка (`"..."` или `'...'`) — всегда скаляр,
        # даже если внутри есть `:` (типичный кейс — `- "warning: text"`).
        rest_stripped = rest.strip()
        is_quoted = (
            len(rest_stripped) >= 2
            and rest_stripped[0] in ('"', "'")
            and rest_stripped[-1] == rest_stripped[0]
        )
        if is_quoted:
            items.append(_parse_scalar(rest))
            i += 1
            continue
        # Нецитированный скаляр: `- ` без `:` снаружи означает скаляр.
        if rest_stripped and ":" not in rest.split("#", 1)[0]:
            items.append(_parse_scalar(rest))
            i += 1
            continue
        # Вложенный mapping под `-`: собираем дочерние строки до следующего
        # `- ` на base_indent или конца блока.
        mapping_lines = [(" " * (base_indent + 2)) + rest] if rest.strip() else []
        j = i + 1
        while j < len(child_lines):
            nxt = child_lines[j]
            if not nxt.strip():
                mapping_lines.append("")
                j += 1
                continue
            nxt_indent = len(nxt) - len(nxt.lstrip(" "))
            if nxt_indent <= base_indent:
                break
            mapping_lines.append(nxt)
            j += 1
        if mapping_lines:
            sub, sub_warn = _parse_block_mapping(mapping_lines, base_indent + 2)
            warnings.extend(sub_warn)
            items.append(sub)
        else:
            items.append(None)
        i = j
    return items


def _parse_block_mapping(lines: list[str], base_indent: int) -> tuple[dict, list[str]]:
    """Распарсить block-mapping на заданном отступе."""
    out: dict = {}
    warnings: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < base_indent:
            break
        if indent != base_indent:
            warnings.append(f"unexpected mapping indent: {line!r}")
            i += 1
            continue
        stripped = line[base_indent:]
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", stripped)
        if not m:
            warnings.append(f"unparseable mapping line: {line!r}")
            i += 1
            continue
        key, value = m.group(1), m.group(2)
        if value.strip():
            out[key] = _parse_scalar(value)
            i += 1
            continue
        # Вложенный блок под этим ключом.
        j = i + 1
        child_lines: list[str] = []
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                child_lines.append("")
                j += 1
                continue
            if (len(nxt) - len(nxt.lstrip(" "))) <= base_indent:
                break
            child_lines.append(nxt)
            j += 1
        first_real = next((c for c in child_lines if c.strip()), "")
        if first_real.lstrip().startswith("- "):
            child_indent = len(first_real) - len(first_real.lstrip(" "))
            out[key] = _parse_block_list(child_lines, child_indent, warnings)
        elif first_real:
            child_indent = len(first_real) - len(first_real.lstrip(" "))
            sub, sub_warn = _parse_block_mapping(child_lines, child_indent)
            warnings.extend(sub_warn)
            out[key] = sub
        else:
            out[key] = None
        i = j
    return out, warnings


# ---------------------------------------------------------------------------
# Markdown body — дерево секций
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Section:
    """Один markdown-блок-секция (H2/H3/...)."""
    level: int
    heading: str
    body: str = ""
    subsections: list["Section"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "heading": self.heading,
            "body": self.body,
            "subsections": [s.to_dict() for s in self.subsections],
        }


_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    """Char-диапазоны fenced-код-блоков (```/~~~) — чтобы `## …` внутри кода
    не принимался за заголовок секции. Незакрытый фенс — до конца текста."""
    ranges: list[tuple[int, int]] = []
    in_fence = False
    start = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            if not in_fence:
                in_fence = True
                start = offset
            else:
                in_fence = False
                ranges.append((start, offset + len(line)))
        offset += len(line)
    if in_fence:
        ranges.append((start, offset))
    return ranges


def parse_sections(body: str) -> tuple[str | None, list[Section]]:
    """Вернуть (title, top_level_sections).

    `title` — текст первого H1 (если есть). Top-level — все H2-блоки.
    H3+ попадают в `subsections` рекурсивно. Всё, что идёт ДО первого H2
    (но после опционального H1), в дерево секций не попадает — оно
    остаётся в исходном `body` на родительском dict'е.

    Заголовки внутри fenced-код-блоков игнорируются (иначе `## …` в примере
    кода порвал бы дерево секций).
    """
    fenced = _fenced_ranges(body)
    matches = [m for m in _HEADER_RE.finditer(body)
               if not any(s <= m.start() < e for s, e in fenced)]
    if not matches:
        return None, []

    title: str | None = None
    sections: list[Section] = []
    stack: list[Section] = []

    # entry = (level, heading, start_of_body, end_of_body)
    entries: list[tuple[int, str, int, int]] = []
    for idx, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2).strip()
        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        entries.append((level, heading, body_start, body_end))

    for level, heading, b_start, b_end in entries:
        sect_body = body[b_start:b_end].strip("\n")
        # Первый H1 трактуем как заголовок документа, в дерево не кладём.
        if level == 1 and title is None and not sections:
            title = heading
            continue
        sect = Section(level=level, heading=heading, body=sect_body)
        if level == 2:
            sections.append(sect)
            stack = [sect]
        else:
            # Родитель = ближайшая в стеке секция с уровнем меньше нашего.
            while stack and stack[-1].level >= level:
                stack.pop()
            if stack:
                stack[-1].subsections.append(sect)
            else:
                # Сирота H3+ до любого H2 — выкатываем в top-level, чтобы не терять.
                sections.append(sect)
            stack.append(sect)
    return title, sections


# ---------------------------------------------------------------------------
# Публичные entry-points
# ---------------------------------------------------------------------------


def parse_stage_file(path: str | Path) -> dict:
    """Распарсить файл стадии с диска."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_stage_text(text)


# Защитная нормализация делиметра на входе экспорта: сырой `-----` (частый
# дрейф DR/Stage 1–2) → `---`, иначе `split_frontmatter` теряет весь YAML.
# Канонический полный нормализатор — `scripts/normalize.py` (delimiter+$+tidy);
# здесь только парс-релевантная часть (делиметр), чтобы не тянуть зависимость.
_DELIM_NORMALIZE_RE = re.compile(r"^[ \t]*-{4,}[ \t]*$", re.MULTILINE)


def parse_stage_text(text: str) -> dict:
    """Распарсить markdown-стадию из строки."""
    text = _DELIM_NORMALIZE_RE.sub("---", text)
    yaml_raw, body = split_frontmatter(text)
    frontmatter, warnings = parse_yaml(yaml_raw) if yaml_raw else ({}, [])
    title, sections = parse_sections(body)
    return {
        "frontmatter": frontmatter,
        "frontmatter_raw": yaml_raw,
        "frontmatter_warnings": warnings,
        "body": body,
        "title": title,
        "sections": [s.to_dict() for s in sections],
        "trip_id": frontmatter.get("trip_id"),
        "stage": frontmatter.get("stage"),
    }


def parse_md_paste(text: str) -> dict:
    """Fallback для DOCX round-trip при paste markdown-текстом.

    Ведёт себя идентично `parse_stage_text` — markdown остаётся markdown.
    Разница важна только для downstream diff/merge-логики (Step 3+):
    md-paste source трактуется как «потенциально структурно дрейфующий»
    и может потребовать fuzzy-сопоставление заголовков с оригиналом.
    """
    return parse_stage_text(text)


def parse_docx_for_import(path: str | Path) -> dict:
    """Извлечь значения из заполненного DOCX (round-trip).

    **Реализация — per-stage**, не в engine: структура form-полей у
    каждой стадии своя. Stage 3 парсит свой DOCX через
    `stages.stage3.parse_docx_for_import` (bookmarks `region_<slug>` /
    `poi_<num>` → теги регионов + комментарии POI).

    Точка входа для пользователя — `export.py --import FILE`, который
    маршрутизирует в нужный stage-модуль по имени файла.
    """
    raise NotImplementedError(
        "parse_docx_for_import — per-stage. Для Stage 3: "
        "stages.stage3.parse_docx_for_import или CLI `export.py --import`."
    )


def find_section(parsed: dict, heading: str) -> dict | None:
    """Найти top-level (H2) секцию по точному совпадению заголовка.

    Удобство для recipient-адаптеров, которые работают с именованными
    ##-секциями (например, «План реагирования на риски»). Возвращает
    словарь секции или None.
    """
    for s in parsed.get("sections", []):
        if s["heading"] == heading:
            return s
    return None

"""stages/stage2.py — экстрактор контента + PDF/HTML builders для Stage 2.

Stage 2 — similarity-фильтр авторов DR-базы (Stage 1) по профилю
путешественников. Каждый автор получает score 0–10 по 6 компонентам
(style/focus/pace/independence/depth/demo) и категорию
HIGH / MEDIUM / LOW / OUTLIER / UNSCORED.

Два формата экспорта, у каждого своя роль:

  • **PDF** (default, светлая тема) — статичная scoring-витрина по
    категориям на общем reportlab-движке (как Stage 1/4/5, паттерн
    cards-стадии pdf-visual-language §11/§12). Только scoring: cover +
    распределение → warnings → reading list карточками (HIGH → OUTLIER →
    MEDIUM-ext) → UNSCORED → полная таблица → MEDIUM/LOW компактно.
    Практику НЕ показывает — она дублировала бы отдельный Stage 1 PDF.

  • **HTML** (тёмная тема) — рабочий lookup-инструмент: фильтр по
    категориям, сортировка по score / # отчёта, click-to-expand с табами
    «Scoring» (C1–C6 + Тянет вверх/вниз) и «Практика» (hidden gems /
    предупреждения / ключевые POI автора). Таб «Практика» заполняется
    из `1_dr_reports.md` (поля 14/15/18 DR-карточек), матчинг по URL.
    Если Stage 1 рядом нет — таб тихо исчезает (graceful degradation).

Источник scoring — `2_similarity.md` (markdown body, не YAML — §6/§8 spec).
Парсер устойчив к двум формам строки компонентов:
  • reading-list:  `C1 style 8→2.0 · C2 focus 10→2.5 · …` (с именами)
  • компактной:    `C1 8→2.22 · C2 3→0.83 · …`            (без имён)
и к null-компонентам (`C6 —` или `C6 demo —`).
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
    from export import adapter as _adapter   # type: ignore[no-redef]  # noqa: F401
    from export import pdf_lib                # type: ignore[no-redef]
    from export import renderer as _renderer  # type: ignore[no-redef]
    from export import cover_common            # type: ignore[no-redef]
    from export import travelers as _travelers  # type: ignore[no-redef]
    from export import html_lib                # type: ignore[no-redef]
    from export.style import COLORS, SIMILARITY_CARD_COLORS  # type: ignore[no-redef]
    from export.stages.stage1 import _humanize_regions, _season_from_trip_id  # type: ignore[no-redef]
else:
    from .. import adapter as _adapter  # noqa: F401
    from .. import pdf_lib
    from .. import renderer as _renderer
    from .. import cover_common
    from .. import travelers as _travelers
    from .. import html_lib
    from ..style import COLORS, SIMILARITY_CARD_COLORS
    from .stage1 import _humanize_regions, _season_from_trip_id

# taxonomy — словарь таксонов (scripts/taxonomy.py). Лежит на уровень выше
# пакета export; путь к scripts/ уже на sys.path (тесты/standalone-блоки),
# defensive-fallback добавляет его, если запуск экзотический.
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import taxonomy


def _ru(text: str | None) -> str:
    """Русификация видимых англицизмов прозы (score → балл, reading list → …).

    Проза Stage 2 (контекст, warnings) приходит от модели с англицизмами;
    единый русификатор — `html_lib.ru_anglicisms`, тот же, что и в HT-ветке
    (Р7) и в баннере интерактивного HTML. Данные не трогаем — только видимый
    текст на выводе."""
    return html_lib.ru_anglicisms(text or "")


def _canon_author_cat(text: str) -> str:
    """Ярлык категории автора (EN/RU) → канонический EN-ключ ('HIGH' …).

    Нерезолвимый текст возвращается как есть (как было до двуязычия)."""
    return taxonomy.canon("author_category", text) or (text or "").strip()


def _ac(key: str) -> str:
    """Русифицированный ярлык категории автора по каноническому EN-ключу."""
    return taxonomy.label("author_category", key)


# ---------------------------------------------------------------------------
# Категории и их цвета (см. style.SIMILARITY_COLORS / макет HTML)
# ---------------------------------------------------------------------------

# Канонические категории Stage 2 (stage2-similarity.md §6.7).
CATEGORIES = ("HIGH", "OUTLIER", "MEDIUM", "LOW", "UNSCORED")

# Светлая палитра для PDF (рамка карточки + badge) — из style.py. Тёмная тема
# HTML задаётся CSS-переменными в шаблоне.
CAT_PDF_COLORS = SIMILARITY_CARD_COLORS

# Полные имена 6 компонентов (для компактной формы строки без имён).
COMPONENT_NAMES = ["style", "focus", "pace", "independence", "depth", "demo"]

# Русские понятные метки компонентов (idx 1..6) — для вывода в PDF/HTML.
# Английские style/focus/independence несведущему человеку непонятны.
COMPONENT_LABELS_RU = {
    1: "Стиль", 2: "Фокус", 3: "Темп",
    4: "Самостоятельность", 5: "Глубина", 6: "Состав",
}


# ---------------------------------------------------------------------------
# Polish-маркер `[[поездка: …]]` — общий со Stage 0/1/4 (шапка обложки)
# ---------------------------------------------------------------------------

_TRIP_MARKER_RE = re.compile(r"\[\[\s*поездка:\s*(.+?)\s*\]\]", re.IGNORECASE | re.DOTALL)


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
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Component:
    """Один из 6 компонентов similarity-score."""
    idx: int                      # 1..6
    name: str | None              # style/focus/… (None в компактной форме)
    value: float | None           # 0..10 или None (компонент = «—»)
    contribution: float | None    # вклад value × eff_weight/100 или None

    @property
    def canon_name(self) -> str:
        """Каноническое имя компонента (восстанавливается по idx)."""
        if self.name:
            return self.name
        return COMPONENT_NAMES[self.idx - 1] if 1 <= self.idx <= 6 else f"c{self.idx}"


@dataclass
class Author:
    """Автор с разбивкой scoring. Поля заполняются из разных секций файла."""
    name: str
    score: float | None = None
    category: str = "MEDIUM"      # HIGH/OUTLIER/MEDIUM/LOW/UNSCORED
    extended: bool = False        # MEDIUM ≥ 6.5 (в расширенном reading list)
    url: str | None = None
    components: list[Component] = field(default_factory=list)
    signal: str | None = None     # OUTLIER SIGNAL
    pull_up: str | None = None    # «Тянет вверх»
    pull_down: str | None = None  # «Тянет вниз»
    tag_marker: str | None = None # компактный one-liner (MED/LOW)
    user_added: bool = False
    low_confidence: tuple[int, int] | None = None  # (known, 6)
    confidence_label: str | None = None            # partial / low
    components_known: int | None = None            # для UNSCORED-блока
    # Заполняется только для HTML из 1_dr_reports.md (enrich_with_practical).
    practical: dict[str, Any] | None = None

    def comp_str(self) -> str:
        """Строка компонентов `C1 Стиль 8→2.0 · …` (русские метки) для PDF."""
        parts = []
        for c in self.components:
            label = COMPONENT_LABELS_RU.get(c.idx, c.canon_name)
            if c.value is None:
                parts.append(f"C{c.idx} {label} —")
            else:
                parts.append(f"C{c.idx} {label} {_fmt_num(c.value)}→{_fmt_num(c.contribution)}")
        return " · ".join(parts)


@dataclass
class Stage2Content:
    """Распарсенный Stage 2 — общий вход для PDF и HTML builders."""
    trip_id: str = ""
    title: str = "Stage 2 — Similarity filter"
    context: str = ""
    trip_marker: dict = field(default_factory=dict)
    distribution: list[tuple[str, str, str]] = field(default_factory=list)  # (категория, кол-во, доля)
    confidence_line: str = ""
    warnings: list[str] = field(default_factory=list)
    high: list[Author] = field(default_factory=list)
    outlier: list[Author] = field(default_factory=list)
    extended: list[Author] = field(default_factory=list)
    unscored_with_signal: list[Author] = field(default_factory=list)
    compact: list[Author] = field(default_factory=list)   # MEDIUM/LOW не в reading list
    full_table: list[Author] = field(default_factory=list)  # все авторы (overview)
    yaml: dict = field(default_factory=dict)
    input_path: "Path | None" = None

    def reading_list(self) -> list[Author]:
        """HIGH + OUTLIER + extended (в порядке секций reading list)."""
        return [*self.high, *self.outlier, *self.extended]

    def all_detailed(self) -> list[Author]:
        """Все авторы с детальным scoring (reading list + компактные)."""
        return [*self.reading_list(), *self.unscored_with_signal, *self.compact]


# ---------------------------------------------------------------------------
# Парсинг-хелперы
# ---------------------------------------------------------------------------


def _fmt_num(x: float | None) -> str:
    """Число без лишних нулей: 2.0 → «2.0», 0.45 → «0.45», 8 → «8»."""
    if x is None:
        return "—"
    if x == int(x):
        # value-часть пишем целым (8, 10), contribution оставляем как есть.
        return str(int(x)) if abs(x) >= 1 or x == 0 else f"{x:g}"
    return f"{x:g}"


# Стрелка между value и contribution: Unicode `→` или ASCII `->` (старый формат).
_ARROW = r"(?:→|->)"

# Один компонент: `C1 style 8→2.0` | `C1 8->2.0` | `C6 demo —` | `C6 —`.
# Null-форма (`—`/`-`) требует границы после, иначе `-` съел бы дефис стрелки.
_COMPONENT_RE = re.compile(
    r"C(?P<idx>\d)\s+"
    r"(?:(?P<name>[A-Za-z_]+)\s+)?"
    r"(?:(?P<value>\d+(?:\.\d+)?)\s*" + _ARROW + r"\s*(?P<contrib>-?\d+(?:\.\d+)?)"
    r"|(?P<null>[—–-])(?=\s|$))"
)


def parse_components(line: str) -> list[Component]:
    """Распарсить строку компонентов в список Component (обе формы)."""
    out: list[Component] = []
    for m in _COMPONENT_RE.finditer(line):
        idx = int(m.group("idx"))
        name = m.group("name")
        if m.group("value") is None:
            out.append(Component(idx=idx, name=name, value=None, contribution=None))
        else:
            out.append(Component(
                idx=idx, name=name,
                value=float(m.group("value")),
                contribution=float(m.group("contrib")),
            ))
    return out


# Заголовок автора-блока (имя в `**…**` опционально — встречаются обе формы):
#   `#1 **helvhrav** — 8.45/10 [user_added]`
#   `#1 Дария «Orange Traveler» — 8.12/10`
#   `#3 **Elita** — 6.00/10 [confidence: partial, 5/6]`
#   `#12 **Orange Traveler (Мария)** — 6.33/10 (MEDIUM)`
# Score якорится в конце (`— N.NN/10`), поэтому ленивое имя через backtracking
# корректно пропускает «—» внутри самого имени.
_AUTHOR_HEAD_RE = re.compile(
    r"^#(?P<rank>\d+)\s+\*{0,2}(?P<name>.+?)\*{0,2}\s*[—–-]\s*"
    r"(?P<score>[\d.]+)/10\s*(?P<trailer>.*)$"
)

# URL-строка: начинается с (опц. `<`) http-ссылки; допускается хвостовая
# аннотация после пробела (`…id_39487 (+ id_39561 — 3 карточки)`).
_URL_LINE_RE = re.compile(r"^\s*<?(?P<url>https?://\S+?)>?(?:\s.*)?$")
_LOW_CONF_RE = re.compile(r"\[(?:low_)?confidence:\s*(?:\w+,\s*)?(\d+)/(\d+)\]|\[(\d+)/(\d+)\]")
_CAT_PAREN_RE = re.compile(rf"\(({taxonomy.pattern('author_category')})\)")
# Ярлык категории внутри ячейки «Категория» полной таблицы (`HIGH`,
# `MEDIUM ext.`, `СРЕДНЯЯ расш.`, `ВЫСОКАЯ [4/6]`) — двуязычно.
_CAT_CELL_RE = re.compile(rf"({taxonomy.pattern('author_category')})", re.IGNORECASE)


def _parse_trailer(trailer: str, author: Author) -> None:
    """Разобрать хвост заголовка: [user_added] / [confidence] / (CATEGORY)."""
    if "[user_added]" in trailer:
        author.user_added = True
    mlc = _LOW_CONF_RE.search(trailer)
    if mlc:
        known = int(mlc.group(1) or mlc.group(3))
        total = int(mlc.group(2) or mlc.group(4))
        author.low_confidence = (known, total)
        mlabel = re.search(r"confidence:\s*(\w+)", trailer)
        if mlabel:
            author.confidence_label = mlabel.group(1)
    mcat = _CAT_PAREN_RE.search(trailer)
    if mcat:
        author.category = _canon_author_cat(mcat.group(1))


def _parse_author_block(block: str, *, default_category: str) -> Author:
    """Распарсить блок одного автора (от `#N **name**` до URL)."""
    lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
    author = Author(name="", category=default_category)
    if not lines:
        return author

    head = _AUTHOR_HEAD_RE.match(lines[0])
    if head:
        author.name = head.group("name").strip()
        try:
            author.score = float(head.group("score"))
        except ValueError:
            author.score = None
        _parse_trailer(head.group("trailer") or "", author)
    else:
        author.name = lines[0].strip("# *")

    # Строка компонентов может быть перенесена на 2 физических строки
    # (`C1 … C3 ·` / `C4 … C6`) — собираем все `C\d…`-строки в один буфер.
    comp_parts: list[str] = []
    for ln in lines[1:]:
        s = ln.strip()
        if not s or s.strip("`") == "":
            # Пустая строка или markdown code-fence (```), которым исходник
            # иногда оборачивает блоки авторов — игнорируем.
            continue
        if re.fullmatch(r"[-—–\s]+", s):
            # Строка-разделитель (`---`/`—`) без резюме у карточки — не
            # рационале, парсер раньше принимал её за tag_marker → «---»
            # всплывало в интерактивном HTML как «почему» карточки.
            continue
        if re.match(r"^C\d", s):
            comp_parts.append(s)
        elif s.startswith("SIGNAL:"):
            author.signal = s[len("SIGNAL:"):].strip()
        elif s.startswith("Тянет вверх:"):
            author.pull_up = s[len("Тянет вверх:"):].strip()
        elif s.startswith("Тянет вниз:"):
            author.pull_down = s[len("Тянет вниз:"):].strip()
        elif s.startswith("components_known"):
            mk = re.search(r"components_known\s*=\s*(\d+)", s)
            if mk:
                author.components_known = int(mk.group(1))
        else:
            mu = _URL_LINE_RE.match(ln)
            if mu:
                author.url = mu.group("url")
            else:
                # Компактный tag-marker (строка-характеристика MED/LOW).
                if author.tag_marker:
                    author.tag_marker += " " + s
                else:
                    author.tag_marker = s
    if comp_parts:
        author.components = parse_components(" ".join(comp_parts))
    return author


def _split_author_blocks(section_text: str) -> list[str]:
    """Разбить текст секции на блоки авторов по строкам `#N **…**`."""
    if not section_text:
        return []
    # Позиции начал блоков (`#N …` — имя в `**` опционально).
    idxs = [m.start() for m in re.finditer(r"^#\d+\s+\S", section_text, re.MULTILINE)]
    if not idxs:
        return []
    idxs.append(len(section_text))
    return [section_text[idxs[i]:idxs[i + 1]].strip() for i in range(len(idxs) - 1)]


# ---------------------------------------------------------------------------
# Извлечение секций из body
# ---------------------------------------------------------------------------


def _split_h2_sections(body: str) -> dict[str, str]:
    """body → {заголовок H2 (lower, без счётчиков): текст до следующего H2}."""
    out: dict[str, str] = {}
    parts = re.split(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    # parts[0] — преамбула (H1), далее пары (заголовок, тело).
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        text = parts[i + 1] if i + 1 < len(parts) else ""
        out[_norm_h2(title)] = text
    return out


def _norm_h2(title: str) -> str:
    """Нормализовать H2 для матчинга (срезать счётчики/хвосты)."""
    t = title.lower().strip()
    t = re.sub(r"\s*\(.*?\)\s*$", "", t)   # убрать «(N авторов)»
    t = re.sub(r"\s*для stage 3.*$", "", t)
    return t.strip()


def _find_section(sections: dict[str, str], *keywords: str) -> str:
    """Найти секцию, заголовок которой содержит все ключевые слова."""
    for title, text in sections.items():
        if all(kw in title for kw in keywords):
            return text
    return ""


def _split_h3_subsections(text: str) -> list[tuple[str, str]]:
    """text → [(заголовок H3, тело)] в порядке появления."""
    out: list[tuple[str, str]] = []
    parts = re.split(r"^###\s+(.+?)\s*$", text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), parts[i + 1] if i + 1 < len(parts) else ""))
    return out


def _parse_distribution(text: str) -> list[tuple[str, str, str]]:
    """Таблица распределения → [(категория, кол-во, доля)]."""
    rows: list[tuple[str, str, str]] = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) != 3:
            continue
        cat, cnt, share = cells
        if cat.lower().startswith("категори") or set(cat) <= set("-—"):
            continue
        rows.append((cat.replace("**", ""), cnt.replace("**", ""), share.replace("**", "")))
    return rows


def _parse_full_table(text: str) -> list[Author]:
    """Полная таблица `| # | Автор | Score | Категория | URL |` → [Author]."""
    out: list[Author] = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.split("|")]
        cells = [c for c in cells if c != ""]
        if len(cells) < 4:
            continue
        if cells[0] in ("#",) or set(cells[0]) <= set("-—"):
            continue
        if not re.match(r"^\d+$", cells[0]):
            continue
        _num, name, score, category = cells[0], cells[1], cells[2], cells[3]
        url = cells[4] if len(cells) >= 5 else None
        if url:
            mu = re.search(r"https?://\S+?(?=>|$)", url)
            url = mu.group(0) if mu else url.strip("<> ")
        a = Author(name=name.strip(), category="MEDIUM", url=url)
        try:
            a.score = float(score)
        except ValueError:
            a.score = None
        cat_up = category.upper()
        # `MEDIUM ext.` / `СРЕДНЯЯ расш.` — маркер расширенного reading list.
        if "EXT" in cat_up or "РАСШ" in cat_up:
            a.extended = True
        # Ярлык категории в ячейке двуязычен (Фаза 2b: тело по-русски).
        mcat = _CAT_CELL_RE.search(category)
        if mcat:
            a.category = _canon_author_cat(mcat.group(1))
        ml = re.search(r"\[(\d+)/(\d+)\]", category)
        if ml:
            a.low_confidence = (int(ml.group(1)), int(ml.group(2)))
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Главный экстрактор
# ---------------------------------------------------------------------------


def extract_content(parsed: dict, *, input_path: "Path | None" = None) -> Stage2Content:
    """parsed (parser.parse_stage_file) → Stage2Content. Markdown body — primary.

    `input_path` — путь к артефакту или список путей-кандидатов (опц.), нужен только
    для резолвера «Кто едет» (профиль/`trip.yaml` относительно него, Р10)."""
    body = parsed.get("body") or ""
    fm = parsed.get("frontmatter") or {}
    content = Stage2Content(
        trip_id=parsed.get("trip_id") or fm.get("trip_id") or "",
        yaml=fm,
        trip_marker=_parse_trip_marker(body),
        input_path=input_path,
    )

    # Заголовок H1.
    if parsed.get("title"):
        content.title = parsed["title"].strip()

    sections = _split_h2_sections(body)

    content.context = _find_section(sections, "контекст").strip()
    # Сырой стем профиля в прозе контекста («группа `алексей_родители`») →
    # резолвнутое имя; машинному идентификатору не место в user-facing выводе.
    who = _travelers.resolve_travelers(fm, content.trip_marker, input_path)
    content.context = _travelers.replace_profile_stem(content.context, fm, who)
    content.distribution = _parse_distribution(_find_section(sections, "распределение"))

    conf = _find_section(sections, "распределение")
    mconf = re.search(r"\*\*Confidence:\*\*\s*(.+)", conf)
    if mconf:
        content.confidence_line = mconf.group(1).strip()

    # Warnings: предпочитаем YAML, fallback на тело.
    yaml_warns = fm.get("warnings")
    if isinstance(yaml_warns, list) and yaml_warns:
        content.warnings = [str(w).strip() for w in yaml_warns if str(w).strip()]
    else:
        warn_text = _find_section(sections, "warning")
        content.warnings = _parse_warning_bullets(warn_text)
    # Хвост-ссылка на внутренний референс скилла («См. stage3-poi.md §6.5.»)
    # читателю не нужен и недоступен — та же природа, что и Stage 3.
    content.warnings = [cover_common.strip_internal_refs(w) for w in content.warnings]

    # Reading list: H3-подсекции «Обязательные (HIGH)», «OUTLIER», «Расширенный».
    rl_text = _find_section(sections, "reading list") or _find_section(sections, "reading")
    for h3, sub in _split_h3_subsections(rl_text):
        h3l = h3.lower()
        if "high" in h3l or "обязательн" in h3l or "высок" in h3l:
            content.high = [_parse_author_block(b, default_category="HIGH")
                            for b in _split_author_blocks(sub)]
        elif "outlier" in h3l or "особый" in h3l:
            content.outlier = [_parse_author_block(b, default_category="OUTLIER")
                               for b in _split_author_blocks(sub)]
        elif "расширенн" in h3l or "extended" in h3l:
            ext = [_parse_author_block(b, default_category="MEDIUM")
                   for b in _split_author_blocks(sub)]
            for a in ext:
                a.extended = True
            content.extended = ext

    # UNSCORED с сигналом.
    uns_text = _find_section(sections, "unscored") or _find_section(sections, "без оценки")
    if uns_text and "нет таких" not in uns_text.lower():
        content.unscored_with_signal = [
            _parse_author_block(b, default_category="UNSCORED")
            for b in _split_author_blocks_unscored(uns_text)
        ]

    # Полная таблица.
    content.full_table = _parse_full_table(_find_section(sections, "полная таблица"))

    # Компактный per-author (MEDIUM/LOW не в reading list).
    compact_text = _find_section(sections, "per-author") or _find_section(sections, "компактн")
    compact: list[Author] = []
    subs = _split_h3_subsections(compact_text)
    if subs:
        for _h3, sub in subs:
            compact.extend(_parse_author_block(b, default_category="MEDIUM")
                           for b in _split_author_blocks(sub))
    else:
        compact.extend(_parse_author_block(b, default_category="MEDIUM")
                       for b in _split_author_blocks(compact_text))
    # Категорию для компактных уточняем из заголовка (там «(MEDIUM)»/«(LOW)»)
    # — она уже разобрана в _parse_trailer.
    content.compact = compact

    return content


def _split_author_blocks_unscored(text: str) -> list[str]:
    """UNSCORED-блок использует `**name**` без `#N` префикса."""
    idxs = [m.start() for m in re.finditer(r"^\*\*", text, re.MULTILINE)]
    if not idxs:
        return _split_author_blocks(text)
    idxs.append(len(text))
    return [text[idxs[i]:idxs[i + 1]].strip() for i in range(len(idxs) - 1)]


def _parse_warning_bullets(text: str) -> list[str]:
    """Извлечь bullets из секции Warnings (срезать эмодзи-маркеры)."""
    out: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("-"):
            continue
        s = s.lstrip("-").strip()
        s = re.sub(r"^[⚠️ℹ️ℹ️\s]+", "", s).strip()
        if s and "без замечаний" not in s.lower():
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Cover / общие хелперы
# ---------------------------------------------------------------------------

import datetime as _dt  # noqa: E402


def _slug(text: str) -> str:
    """Безопасный slug для anchor из имени автора."""
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return s[:60] or "author"


def _who_goes(content: Stage2Content) -> str:
    """«Кто едет» — единый резолвер (Р10): профиль display_name → trip.yaml →
    trip-маркер polish'а → имя файла профиля."""
    who = _travelers.resolve_travelers(content.yaml, content.trip_marker,
                                       content.input_path)
    return who or "—"


def _cover_title(content: Stage2Content) -> str:
    """`{Регионы} · Похожие авторы` — человекочитаемый заголовок.

    Если polish дал чистый H1 (не «Stage 2 — …») — используем его.
    """
    raw = (content.title or "").strip()
    if raw and not re.search(r"^#?\s*stage\s*\d|similarity\s+filter", raw, re.IGNORECASE):
        return raw
    regions = content.trip_marker.get("регионы")
    if not regions:
        regions = _humanize_regions(content.trip_id)
    return f"{regions} · Похожие авторы" if regions else "Похожие авторы"


def _cover_subtitle(content: Stage2Content) -> str:
    """Подзаголовок обложки из trip-маркера polish'а (`[[поездка: …]]`).

    Без маркера подзаголовок пуст — заголовок уже несёт регионы, а полный
    контекст идёт info-box'ом ниже (не дублируем первую фразу контекста).
    """
    tm = content.trip_marker
    if tm:
        bits = [tm.get(k) for k in ("длительность", "сезон") if tm.get(k)]
        if bits:
            return " · ".join(bits)
    return ""


# Расшифровка confidence-уровней (доля из 6 критериев, оценённых у автора).
_CONF_RU = {"full": "полные", "partial": "частичные", "low": "мало данных",
            "unscored": "без оценки"}


def _confidence_decoded(content: Stage2Content) -> str | None:
    """`full=33 · partial=3 · …` → «полные (6/6): 33 · частичные (4–5/6): 3 · …»."""
    line = content.confidence_line
    if not line:
        return None
    detail = {"full": "6/6", "partial": "4–5/6", "low": "3/6", "unscored": "<3/6"}
    out: list[str] = []
    for m in re.finditer(r"(\w+)\s*=\s*(\d+)", line):
        key, n = m.group(1), m.group(2)
        if int(n) == 0:
            continue
        ru = _CONF_RU.get(key, key)
        out.append(f"{ru} ({detail.get(key, '')}): {n}")
    return " · ".join(out) if out else None


def _cover_key_params(content: Stage2Content) -> list[tuple[str, str]]:
    """Строки key_params_table обложки (паспорт поездки + сводка выборки).

    Архетип / веса / пороги НЕ выводим — это внутренняя методология,
    пользователю не информативна.
    """
    fm = content.yaml
    rows = cover_common.passport_rows(
        who=_who_goes(content),
        geo=content.trip_marker.get("регионы") or _humanize_regions(content.trip_id),
        season=content.trip_marker.get("сезон") or _season_from_trip_id(content.trip_id),
    )
    total = fm.get("total_authors")
    if total is not None:
        rows.append(("Авторов в выборке", str(total)))
    dist = (f"{_ac('HIGH')} {fm.get('high_similarity_count', '?')} · "
            f"{_ac('OUTLIER')} {fm.get('outlier_count', '?')} · "
            f"{_ac('MEDIUM')} {fm.get('medium_count', '?')} · "
            f"{_ac('LOW')} {fm.get('low_count', '?')} · "
            f"{_ac('UNSCORED')} {fm.get('unscored_count', '?')}")
    rows.append(("Распределение", dist))
    conf = _confidence_decoded(content)
    if conf:
        rows.append(("Полнота оценки (из 6 критериев)", conf))
    return rows


def _badge_for(a: Author) -> tuple[str, str]:
    """(label, color) badge для категории автора (ярлык русифицирован)."""
    return (taxonomy.label("author_category", a.category),
            CAT_PDF_COLORS.get(a.category, CAT_PDF_COLORS["MEDIUM"]))


# Локализация англицизмов в метках, приходящих из исходного файла
# (категории распределения и т.п.).
_LABEL_RU = [
    (r"\bborderline\b", "пограничные"),
    (r"\bscore\b", "балл"),
    (r"\bsignal\b", "сигнал"),
    (r"components_known", "оценено критериев"),
    (r"\blow total\b", "низкий балл"),
]

# Альтернация EN-ярлыков категорий автора (для ведущего таксона в строке-метке).
_AC_EN_ALT = "|".join(
    re.escape(taxonomy.label("author_category", _k, "en"))
    for _k in taxonomy.keys("author_category")
)


def _localize_label(s: str) -> str:
    """Russify англицизмы в строковой метке (например, категории распределения)."""
    for pat, repl in _LABEL_RU:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    return s


def _localize_dist_category(s: str) -> str:
    """Метка категории в таблице §Распределение: ведущий EN-таксон → русский
    ярлык (`HIGH (балл ≥ 7.0)` → `ВЫСОКАЯ (балл ≥ 7.0)`), затем локализация
    англицизмов. Только для этой таблицы — warning-проза остаётся как есть (Р5)."""
    s = re.sub(
        rf"^\s*({_AC_EN_ALT})\b",
        lambda m: taxonomy.label(
            "author_category",
            taxonomy.canon("author_category", m.group(1)) or m.group(1)),
        s,
    )
    return _localize_label(s)


# Severity-префиксы warnings (из YAML / тела): critical/borderline/warning →
# «предупреждение» (amber), info → «примечание» (нейтральный box).
# Ярлыки двуязычны (Фаза 2b эмитит тело по-русски: `⚠️ критично:` / `ℹ️ инфо:`),
# формы берутся из taxonomy — параллельный словарь заводить нельзя.


def _sev_alt(*keys: str) -> str:
    """Альтернация ярлыков severity (EN+RU) для перечисленных ключей."""
    forms = {taxonomy.label("warning_severity", k, lang)
             for k in keys for lang in ("en", "ru")}
    return "|".join(re.escape(f) for f in sorted(forms, key=lambda s: (-len(s), s)))


_INFO_RE = re.compile(rf"^\s*(?:ℹ️\s*)?(?:{_sev_alt('info')})\s*:\s*", re.IGNORECASE)
_WARN_PREFIX_RE = re.compile(
    rf"^\s*(?:⚠️\s*)?(?:{_sev_alt('critical', 'borderline')}|warning)\s*:\s*",
    re.IGNORECASE)


def _split_warnings_by_severity(warnings: list[str]) -> tuple[list[str], list[str]]:
    """Разделить warnings на (предупреждения, примечания) по severity-префиксу.

    info: → примечания (нейтральный box); critical/borderline/warning →
    предупреждения (amber). Префикс severity срезается — его несёт сам блок.
    """
    warns: list[str] = []
    infos: list[str] = []
    for w in warnings:
        w = str(w).strip()
        if not w:
            continue
        if _INFO_RE.match(w):
            infos.append(_localize_label(_INFO_RE.sub("", w).strip()))
        else:
            warns.append(_localize_label(_WARN_PREFIX_RE.sub("", w).strip()))
    return warns, infos


def _author_meta_line(a: Author) -> str:
    """meta-строка карточки: score + флаги."""
    bits: list[str] = []
    if a.score is not None:
        bits.append(f"**{a.score:g}/10**")
    if a.user_added:
        bits.append("добавлен вручную")
    if a.low_confidence:
        bits.append(f"оценено {a.low_confidence[0]}/{a.low_confidence[1]} критериев")
    return " · ".join(bits)


# Цвета для colored_lines карточки (как в HTML: вверх — зелёный, вниз — красный).
_PULL_UP_COLOR = "#1a7f37"
_PULL_DOWN_COLOR = "#b91c1c"


def _author_card_body(a: Author) -> str:
    """Тело карточки: строка компонентов + URL (markdown-ссылкой)."""
    paras: list[str] = []
    cs = a.comp_str()
    if cs:
        paras.append(cs)
    if a.url:
        # Markdown-ссылка (а не bare-URL): md_inline_to_rl застешит готовый
        # `<a>` и не словит double-wrap на дефисных доменах.
        paras.append(f"[{a.url}]({a.url})")
    return "\n\n".join(paras)


def _author_card(a: Author, accent: str, *, with_signal: bool = False):
    """entity_card одного автора reading-list. SIGNAL/Тянет вверх/вниз —
    цветными метками (как в HTML)."""
    lines: list[tuple[str, str, str]] = []
    if with_signal and a.signal:
        lines.append(("Сигнал:", a.signal, SIMILARITY_CARD_COLORS["OUTLIER"]))
    if a.pull_up:
        lines.append(("Тянет вверх:", a.pull_up, _PULL_UP_COLOR))
    if a.pull_down:
        lines.append(("Тянет вниз:", a.pull_down, _PULL_DOWN_COLOR))
    return pdf_lib.entity_card(
        title=a.name,
        accent_color=accent,
        badge=_badge_for(a),
        meta_line=_author_meta_line(a) or None,
        body=_author_card_body(a),
        colored_lines=lines or None,
        anchor_slug=_slug(a.name),
    )


# ---------------------------------------------------------------------------
# Build PDF (scoring-витрина, светлая тема)
# ---------------------------------------------------------------------------


def build_pdf(content: Stage2Content, output_path: str | Path, *, recipient: str = "self") -> str:
    """Собрать PDF Stage 2 — статичная scoring-витрина по категориям."""
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 2 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    styles = pdf_lib.get_styles()

    doc = pdf_lib.make_doc(
        output_path,
        orientation="portrait",
        title=f"Similarity filter — {content.trip_id}",
    )
    created = content.yaml.get("created") or _dt.date.today().isoformat()
    pdf_lib.set_footer_text(f"создан {created}".strip())

    try:
        story: list[Any] = []

        # ─── 1. Cover ───────────────────────────────────────────────────
        story.append(pdf_lib.heading_paragraph(
            _cover_title(content),
            styles["cover_title"],
        ))
        sub = _cover_subtitle(content)
        if sub:
            story.append(pdf_lib.para(sub, styles["cover_subtitle"]))
        story.append(pdf_lib.spacer(12))
        kp = _cover_key_params(content)
        if kp:
            story.append(pdf_lib.key_params_table(kp))
        if content.context:
            story.append(pdf_lib.spacer(10))
            story.append(pdf_lib.info_box(_ru(content.context), styles))

        # ─── 2. Распределение ───────────────────────────────────────────
        if content.distribution:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Распределение по категориям",
                anchor_slug="distribution", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            dist_rows = [[_localize_dist_category(c), cnt, share]
                         for c, cnt, share in content.distribution]
            rows = [["Категория", "Кол-во", "Доля"], *dist_rows]
            story.append(pdf_lib.data_table(rows, header=True,
                                            col_widths=["60%", "20%", "20%"]))
            # Полнота оценки — уже на обложке, тут не дублируем.

        # ─── 3. Предупреждения и примечания (по severity) ───────────────
        warns, infos = _split_warnings_by_severity(content.warnings)
        if warns:
            story.append(pdf_lib.spacer(8))
            story.append(pdf_lib.para("Предупреждения", styles["h3"], highlight_todo=False))
            story.append(pdf_lib.warning_box_bullets([_ru(w) for w in warns], styles))
        if infos:
            story.append(pdf_lib.spacer(8))
            story.append(pdf_lib.para("Примечания", styles["h3"], highlight_todo=False))
            story.append(pdf_lib.info_box("\n".join(f"• {_ru(i)}" for i in infos), styles))

        # ─── 4. Reading list ────────────────────────────────────────────
        groups = [
            (f"Обязательные — {_ac('HIGH')}", content.high, CAT_PDF_COLORS["HIGH"], False),
            (f"{_ac('OUTLIER')} — уникальный сигнал", content.outlier, CAT_PDF_COLORS["OUTLIER"], True),
            (f"Расширенный список — {_ac('MEDIUM')} ≥ 6.5", content.extended, CAT_PDF_COLORS["MEDIUM"], False),
        ]
        any_rl = any(g[1] for g in groups)
        if any_rl:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Список для чтения (Stage 3)",
                anchor_slug="reading-list", outline_level=0,
            ))
            for label, authors, color, with_signal in groups:
                if not authors:
                    continue
                story.append(pdf_lib.spacer(8))
                story.append(pdf_lib.section_bar(label, bg_color=color))
                story.append(pdf_lib.spacer(6))
                for a in authors:
                    story.append(_author_card(a, color, with_signal=with_signal))
                    story.append(pdf_lib.spacer(6))

        # ─── 5. UNSCORED с сигналом ──────────────────────────────────────
        if content.unscored_with_signal:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Без оценки, но с сигналом",
                anchor_slug="unscored", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            for a in content.unscored_with_signal:
                story.append(_author_card(a, CAT_PDF_COLORS["UNSCORED"], with_signal=True))
                story.append(pdf_lib.spacer(6))

        # ─── 6. Полная таблица всех авторов ──────────────────────────────
        if content.full_table:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                "Полная таблица всех авторов",
                anchor_slug="full-table", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            rows = [["#", "Автор", "Балл", "Категория", "Ссылка"]]
            for i, a in enumerate(content.full_table, 1):
                cat = _ac(a.category) + (" расш." if a.extended else "")
                score = f"{a.score:g}" if a.score is not None else "—"
                url = f"[{a.url}]({a.url})" if a.url else ""
                rows.append([str(i), a.name, score, cat, url])
            story.append(pdf_lib.data_table(
                rows, header=True, col_widths=["6%", "34%", "12%", "18%", "30%"],
            ))

        # ─── 7. MEDIUM / LOW компактно ───────────────────────────────────
        if content.compact:
            story.append(pdf_lib.page_break())
            story.append(pdf_lib.section_bar(
                f"Оценка по авторам ({_ac('MEDIUM')} / {_ac('LOW')})",
                anchor_slug="compact", outline_level=0,
            ))
            story.append(pdf_lib.spacer(6))
            for a in content.compact:
                story.extend(_compact_block(a, styles))

        # ─── Легенда таксонов (Р2): соответствие RU↔EN одной сноской ──────
        story.append(pdf_lib.spacer(10))
        story.append(pdf_lib.para(
            "Категории сходства (RU = EN из исходных артефактов): "
            + taxonomy.legend("author_category"),
            styles["small"], highlight_todo=False))

        pdf_lib.build_doc(doc, story, with_background=True)
        return str(output_path)
    finally:
        pdf_lib.set_footer_text("")
        pdf_lib.clear_section_anchors()


def _compact_block(a: Author, styles: dict) -> list:
    """Компактный per-author блок (MED/LOW): заголовок + компоненты + тег + URL."""
    out: list = []
    cat = _ac(a.category) + (" расш." if a.extended else "")
    score = f"{a.score:g}/10" if a.score is not None else "—"
    head = f"**{a.name}** — {score} ({cat})"
    if a.low_confidence:
        head += f" [оценено {a.low_confidence[0]}/{a.low_confidence[1]}]"
    if a.user_added:
        head += " [добавлен вручную]"
    out.append(pdf_lib.para(head, styles["body"], highlight_todo=False))
    cs = a.comp_str()
    if cs:
        out.append(pdf_lib.para(cs, styles["small"], highlight_todo=False))
    if a.tag_marker:
        out.append(pdf_lib.para(a.tag_marker, styles["body_compact"], highlight_todo=False))
    if a.url:
        out.append(pdf_lib.para(f"[{a.url}]({a.url})", styles["small"], highlight_todo=False))
    out.append(pdf_lib.spacer(6))
    return out


# ---------------------------------------------------------------------------
# Build HTML (тёмная тема, интерактивный lookup)
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402

_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "stage2_similarity.html"

# Компонентный CSS интерактивного lookup Stage 2 — поверх дизайн-токенов
# (`html_lib.head_assets(extra_css=…)`). Тёплая «бумажная» палитра, обе темы
# (токены сами переключаются по data-theme), self-contained IBM Plex. Цвет
# категории проброшен через переменную `--cc` на карточке (DRY: одно правило
# на бар/балл/бейдж/полосу вместо четырёх дублей на каждую категорию).
# Категории → палитра токенов: HIGH бирюза (accent), MEDIUM янтарь (warn),
# LOW нейтраль (muted), ОСОБЫЙ СИГНАЛ синий (info) — без «вырвиглаз».
_STAGE2_CSS = """
*{box-sizing:border-box;}
body{background:var(--canvas);color:var(--ink);font-family:var(--font-body);
  min-height:100vh;line-height:1.6;margin:0;
  --c-high:var(--accent);--c-medium:var(--warn);--c-low:var(--muted);--c-outlier:var(--info);
  --s2pad:40px;}
header{padding:40px var(--s2pad) 28px;border-bottom:1px solid var(--line);background:var(--paper);}
.header-label{font-family:var(--font-mono);font-size:11px;letter-spacing:.16em;color:var(--accent);text-transform:uppercase;margin-bottom:10px;}
h1{font-family:var(--font-display);font-weight:700;letter-spacing:var(--display-ls);font-size:30px;color:var(--ink);line-height:1.2;margin:0 0 6px;}
h1 em{font-style:italic;color:var(--accent);}
.header-sub{font-size:12.5px;color:var(--muted);font-family:var(--font-mono);}
.summary{display:flex;gap:0;padding:20px var(--s2pad);border-bottom:1px solid var(--line);background:var(--paper);flex-wrap:wrap;}
.summary-item{flex:1;min-width:110px;padding:10px 22px 10px 0;border-right:1px solid var(--line);}
.summary-item:last-child{border-right:none;}
.summary-count{font-family:var(--font-display);font-size:34px;font-weight:700;line-height:1;margin-bottom:4px;}
.summary-label{font-family:var(--font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);}
.count-high{color:var(--c-high);}.count-medium{color:var(--c-medium);}
.count-low{color:var(--c-low);}.count-outlier{color:var(--c-outlier);}
.warning-banner{display:flex;align-items:flex-start;gap:12px;padding:11px var(--s2pad);background:var(--warn-bg);border-bottom:1px solid var(--warn-line);font-size:12px;color:var(--warn);font-family:var(--font-body);line-height:1.5;}
.controls{padding:16px var(--s2pad);display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line);align-items:center;background:var(--canvas);}
.filter-label{font-family:var(--font-mono);font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-right:4px;}
.btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;padding:6px 13px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--paper);color:var(--muted);cursor:pointer;transition:all .15s;text-transform:uppercase;}
.btn:hover{border-color:var(--accent);color:var(--accent);}
.btn.active{background:var(--accent);color:var(--plate-fg);border-color:var(--accent);font-weight:600;}
.btn-high.active{background:var(--c-high);border-color:var(--c-high);color:var(--plate-fg);}
.btn-medium.active{background:var(--c-medium);border-color:var(--c-medium);color:var(--plate-fg);}
.btn-low.active{background:var(--c-low);border-color:var(--c-low);color:var(--plate-fg);}
.btn-outlier.active{background:var(--c-outlier);border-color:var(--c-outlier);color:var(--plate-fg);}
.sort-controls{margin-left:auto;display:flex;gap:8px;align-items:center;}
.grid{padding:28px var(--s2pad);display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px;}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:18px;transition:all .2s;cursor:pointer;position:relative;overflow:hidden;--cc:var(--muted);}
.card.high{--cc:var(--c-high);}.card.medium{--cc:var(--c-medium);}
.card.low{--cc:var(--c-low);}.card.outlier{--cc:var(--c-outlier);}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--cc);}
.card:hover{border-color:var(--accent);background:var(--paper);transform:translateY(-1px);}
.card-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:11px;}
.card-num{font-family:var(--font-mono);font-size:10px;color:var(--muted);margin-bottom:3px;}
.card-author{font-weight:600;font-size:14px;color:var(--ink);margin-bottom:2px;}
.card-url{font-family:var(--font-mono);font-size:10px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;text-decoration:none;display:block;}
.card-url:hover{color:var(--accent);}
.score-block{text-align:right;flex-shrink:0;}
.score-num{font-family:var(--font-display);font-size:26px;font-weight:700;line-height:1;color:var(--cc);}
.cat-badge{display:inline-block;font-family:var(--font-mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px;margin-top:4px;color:var(--cc);background:color-mix(in srgb,var(--cc) 12%,transparent);border:1px solid color-mix(in srgb,var(--cc) 32%,transparent);}
.score-bar-row{display:flex;gap:4px;align-items:center;margin-bottom:10px;}
.score-bar-track{flex:1;height:4px;background:var(--line);border-radius:2px;overflow:hidden;}
.score-bar-fill{height:100%;border-radius:2px;background:var(--cc);}
.bar-label{font-family:var(--font-mono);font-size:10px;color:var(--muted);width:18px;text-align:right;flex-shrink:0;}
.tags{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;}
.tag{font-family:var(--font-mono);font-size:10px;padding:2px 6px;border-radius:2px;background:var(--canvas);border:1px solid var(--line);color:var(--muted);}
.card-rationale{font-size:12px;color:var(--muted);line-height:1.55;border-top:1px solid var(--line);padding-top:10px;}
.expanded-details{display:none;margin-top:14px;padding-top:14px;border-top:1px solid var(--line);}
.card.expanded .expanded-details{display:block;}
.tab-bar{display:flex;gap:2px;margin-bottom:14px;}
.tab-btn{font-family:var(--font-mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:var(--radius-sm);border:1px solid var(--line);background:var(--paper);color:var(--muted);cursor:pointer;transition:all .15s;}
.tab-btn:hover{color:var(--ink);border-color:var(--accent);}
.tab-btn.active{background:var(--canvas);color:var(--ink);border-color:var(--accent);}
.tab-pane{display:none;}.tab-pane.active{display:block;}
.comp-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px;}
.comp-item{background:var(--canvas);border:1px solid var(--line);border-radius:var(--radius-sm);padding:8px 10px;}
.comp-name{font-family:var(--font-mono);font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px;}
.comp-score{font-family:var(--font-mono);font-size:18px;font-weight:600;color:var(--ink);}
.comp-contrib{font-family:var(--font-mono);font-size:9px;color:var(--muted);}
.reason{font-size:11.5px;line-height:1.5;margin-bottom:8px;color:var(--ink);}
.reason .reason-label{font-family:var(--font-mono);font-size:9px;letter-spacing:.08em;text-transform:uppercase;margin-right:6px;}
.reason.up .reason-label{color:var(--accent);}
.reason.down .reason-label{color:var(--danger);}
.prac-section{margin-bottom:12px;}
.prac-label{font-family:var(--font-mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px;display:flex;align-items:center;gap:6px;}
.prac-label::after{content:'';flex:1;height:1px;background:var(--line);}
.prac-text{font-size:11.5px;color:var(--muted);line-height:1.5;}
.prac-text.warn{color:var(--danger);}
.prac-text.gem{color:var(--warn);}
.prac-text.photo{color:var(--info);}
.prac-empty{font-family:var(--font-mono);font-size:10px;color:var(--muted);}
.signal-box{margin-top:10px;padding:8px 12px;border-radius:var(--radius-sm);font-size:11px;font-family:var(--font-mono);line-height:1.5;}
.signal-box.outlier{background:color-mix(in srgb,var(--info) 10%,transparent);border:1px solid color-mix(in srgb,var(--info) 30%,transparent);color:var(--info);}
.signal-box.outlier::before{content:'⚡ СИГНАЛ: ';font-weight:600;}
.signal-box.reading{background:color-mix(in srgb,var(--accent) 10%,transparent);border:1px solid color-mix(in srgb,var(--accent) 28%,transparent);color:var(--accent);}
.signal-box.reading::before{content:'📖 СПИСОК ЧТЕНИЯ: ';font-weight:600;}
.reading-section{margin:0 var(--s2pad) 40px;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;}
.reading-header{padding:15px 22px;background:var(--paper);border-bottom:1px solid var(--line);font-family:var(--font-mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);}
.reading-body{padding:18px 22px;display:grid;grid-template-columns:1fr 1fr;gap:20px;}
.reading-group-label{font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:10px;}
.reading-item{padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start;}
.reading-item:last-child{border-bottom:none;}
.reading-score{font-family:var(--font-mono);font-size:13px;font-weight:600;flex-shrink:0;width:36px;color:var(--accent);}
.reading-author{font-size:13px;color:var(--ink);}
.reading-note{font-size:11px;color:var(--muted);margin-top:2px;}
.legend{margin:18px var(--s2pad) 4px;font-size:10px;color:var(--muted);letter-spacing:.03em;}
.card.hidden{display:none;}
footer{padding:22px var(--s2pad) 36px;border-top:1px solid var(--line);font-family:var(--font-mono);font-size:10px;color:var(--muted);letter-spacing:.06em;}
@media (max-width:760px){
  body{--s2pad:18px;}
  .grid{grid-template-columns:1fr;}
  .comp-grid{grid-template-columns:1fr 1fr;}
  .reading-body{grid-template-columns:1fr;}
  .sort-controls{margin-left:0;}
}
"""

# Локализованные имена компонентов для HTML (idx 1..6) — из общей карты.
_COMP_LABELS_RU = [f"C{i} {COMPONENT_LABELS_RU[i]}" for i in range(1, 7)]

# Категория Stage 2 → css-класс макета.
_CAT_CSS = {"HIGH": "high", "OUTLIER": "outlier", "MEDIUM": "medium",
            "LOW": "low", "UNSCORED": "unscored"}


def _norm_url(u: str | None) -> str:
    """Ключ матчинга: url без схемы/www и финального слэша."""
    if not u:
        return ""
    u = re.sub(r"^https?://", "", u.strip())
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/").lower()


def _comps_arrays(a: Author) -> tuple[list, list]:
    """Author.components → (comps[6], contribs[6]) с null для отсутствующих."""
    by_idx = {c.idx: c for c in a.components}
    comps: list = []
    contribs: list = []
    for i in range(1, 7):
        c = by_idx.get(i)
        comps.append(None if (c is None or c.value is None) else c.value)
        contribs.append(None if (c is None or c.contribution is None) else c.contribution)
    return comps, contribs


def _first_phrase(text: str | None) -> str:
    """Первая фраза (до `;`) — короткий тизер для rationale-fallback, не
    весь текст «Тянет вверх» (тот целиком доступен отдельно в поле `up`)."""
    if not text:
        return ""
    return text.split(";", 1)[0].strip()


def _author_tags(a: Author) -> list[str]:
    """Лёгкие chip-теги карточки (не из DR — из метаданных scoring).

    Ярлыки — через taxonomy (`author_tag`), не хардкод EN (Р11): эти строки
    идут прямо в JSON для клиентского JS шаблона Stage 2 (`%%DATA%%`),
    видимый чип рендерится как есть, без своего резолва тегов."""
    tags: list[str] = []
    if a.user_added:
        tags.append(taxonomy.label("author_tag", "user_added"))
    if a.low_confidence:
        tags.append(f"{a.low_confidence[0]}/6 known")
    if a.extended:
        tags.append(taxonomy.label("author_tag", "ext_reading"))
    return tags


def _author_to_js(a: Author, num: int, *, reading: bool) -> dict:
    """Author → dict для JS-массива reports."""
    comps, contribs = _comps_arrays(a)
    # Фронт карточки: компактный tag-marker (MED/LOW) или первая фраза
    # «Тянет вверх» (reading-list) как тизер — чтобы видеть «почему», не
    # раскрывая карточку. Без резюме и без «Тянет вверх» — пусто (не «---»).
    rationale = a.tag_marker or _first_phrase(a.pull_up)
    obj: dict[str, Any] = {
        "num": num,
        "author": a.name,
        "url": a.url or "",
        "cat": _CAT_CSS.get(a.category, "medium"),
        "score": a.score,
        "tags": _author_tags(a),
        "comps": comps,
        "contribs": contribs,
        "rationale": rationale,
        "up": a.pull_up or None,
        "down": a.pull_down or None,
        "outlierSignal": a.signal or None,
        "readingList": reading,
    }
    if reading:
        obj["readingNote"] = ("Расширенный список (MEDIUM ≥ 6.5)"
                              if a.extended else "Обязательный reading list Stage 3")
    if a.practical:
        obj["practical"] = a.practical
    return obj


def _merge_authors(content: Stage2Content) -> list[Author]:
    """Полная таблица (authoritative score/cat/url) + детали по матчингу URL/имени.

    Возвращает список авторов в порядке полной таблицы (score ↓), у каждого —
    components / pull_up/down / signal / tag_marker / practical из детальных
    секций, если нашлось соответствие.
    """
    detail = content.all_detailed()
    by_url = {_norm_url(a.url): a for a in detail if a.url}
    by_name = {a.name.strip().lower(): a for a in detail}

    merged: list[Author] = []
    base = content.full_table or detail
    for a in base:
        d = by_url.get(_norm_url(a.url)) if a.url else None
        if d is None:
            d = by_name.get(a.name.strip().lower())
        if d is None:
            merged.append(a)
            continue
        # Копия base + перенос деталей.
        a.components = d.components or a.components
        a.signal = d.signal or a.signal
        a.pull_up = d.pull_up or a.pull_up
        a.pull_down = d.pull_down or a.pull_down
        a.tag_marker = d.tag_marker or a.tag_marker
        a.user_added = a.user_added or d.user_added
        a.low_confidence = a.low_confidence or d.low_confidence
        if d.practical and not a.practical:
            a.practical = d.practical
        merged.append(a)
    return merged


def _summary_items(content: Stage2Content) -> str:
    """HTML summary-item'ы из YAML-распределения."""
    fm = content.yaml
    cells = [
        ("count-high", fm.get("high_similarity_count"), f"{_ac('HIGH')} ≥7.0"),
        ("count-medium", fm.get("medium_count"), f"{_ac('MEDIUM')} 5–6.9"),
        ("count-low", fm.get("low_count"), f"{_ac('LOW')} &lt;5.0"),
        ("count-outlier", fm.get("outlier_count"), _ac("OUTLIER")),
        ("", fm.get("total_authors"), "Всего"),
    ]
    out = []
    for cls, val, label in cells:
        if val is None:
            continue
        # «Всего» — без цвет-класса: базовый ink (--ink). Раньше был жёсткий
        # #eef2ef (почти белый, наследие тёмной темы) → на светлой бумаге
        # не читался.
        cnum = f'<div class="summary-count {cls}">{val}</div>' if cls \
            else f'<div class="summary-count">{val}</div>'
        out.append(f'<div class="summary-item">{cnum}<div class="summary-label">{label}</div></div>')
    return "\n  ".join(out)


def _warning_banner(content: Stage2Content) -> str:
    if not content.warnings:
        return ""
    # Русификация видимых англицизмов (score/similarity → балл/похожесть) —
    # только этот видимый текст, warnings-данные не трогаем (Р11, §5.4).
    items = " · ".join(
        _html_escape(html_lib.ru_anglicisms(w)) for w in content.warnings)
    return f'<div class="warning-banner"><span>⚠</span><span>{items}</span></div>'


def _reading_section(content: Stage2Content) -> str:
    """Сводный блок reading list (HIGH+OUTLIER слева, extended справа)."""
    def _items(authors: list[Author], color_var: str) -> str:
        rows = []
        for a in authors:
            note = a.tag_marker or (a.pull_up or "")
            note = _html_escape(note[:140])
            score = f"{a.score:g}" if a.score is not None else "—"
            rows.append(
                f'<div class="reading-item"><div class="reading-score" '
                f'style="color:var({color_var})">{score}</div>'
                f'<div><div class="reading-author">{_html_escape(a.name)}</div>'
                f'<div class="reading-note">{note}</div></div></div>'
            )
        return "".join(rows)

    left = ""
    if content.high:
        left += f'<div class="reading-group-label">Обязательные ({_ac("HIGH")})</div>'
        left += _items(content.high, "--high")
    if content.outlier:
        left += (f'<div class="reading-group-label" style="margin-top:16px">{_ac("OUTLIER")}</div>')
        left += _items(content.outlier, "--outlier")
    right = ""
    if content.extended:
        right += f'<div class="reading-group-label">Расширенный ({_ac("MEDIUM")} ≥ 6.5)</div>'
        right += _items(content.extended, "--medium")
    if not (left or right):
        return ""
    return (
        '<div class="reading-section">'
        '<div class="reading-header">📖 Список для детального чтения на Stage 3</div>'
        f'<div class="reading-body"><div>{left}</div><div>{right}</div></div></div>'
    )


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html(content: Stage2Content, output_path: str | Path, *,
               recipient: str = "self", dr_path: str | Path | None = None,
               embed_fonts: bool = True) -> str:
    """Собрать интерактивный HTML Stage 2 (дизайн-система, фильтр/сортировка/expand).

    Палитра/шрифты/тема — из `html_lib.head_assets` (тёплая «бумажная» система,
    светлая и тёмная темы синхронно с кабинетом через `hub-theme`, вшитый
    IBM Plex). `dr_path` — путь к `1_dr_reports.md`: если задан и найден — таб
    «Практика» заполняется (поля 14/15/18/20 DR-карточек, матчинг по URL);
    иначе таб не рендерится (graceful degradation). `embed_fonts=False` —
    ссылаться на ./fonts вместо base64 (серверный пайплайн).
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    # Enrich практикой из Stage 1 (опц.).
    has_practical = False
    if dr_path:
        has_practical = enrich_with_practical(content, dr_path)

    authors = _merge_authors(content)
    reading_urls = {_norm_url(a.url) for a in content.reading_list() if a.url}
    reading_names = {a.name.strip().lower() for a in content.reading_list()}

    js_objs = []
    for num, a in enumerate(authors, 1):
        reading = (_norm_url(a.url) in reading_urls) if a.url else False
        reading = reading or (a.name.strip().lower() in reading_names)
        js_objs.append(_author_to_js(a, num, reading=reading))
    data = ",\n".join(_json.dumps(o, ensure_ascii=False) for o in js_objs)

    weights = content.yaml.get("weights_used") or [25, 25, 15, 10, 15, 10]

    regions = content.trip_marker.get("регионы") or _humanize_regions(content.trip_id)
    season = content.trip_marker.get("сезон") or _season_from_trip_id(content.trip_id)
    header_label = " · ".join(x for x in [regions, season, f"Кто едет: {_who_goes(content)}"]
                              if x and not x.endswith("—")) or content.trip_id
    header_sub = ("Профиль путешественника применён к базе отчётов Stage 1 · "
                  "Клик по карточке — раскрыть детали")
    created = content.yaml.get("created") or _dt.date.today().isoformat()

    replacements = {
        "%%HEAD_ASSETS%%": html_lib.head_assets(
            embed_fonts=embed_fonts, extra_css=_STAGE2_CSS),
        "%%TITLE%%": _html_escape(_cover_title(content)),
        "%%HEADER_LABEL%%": _html_escape(header_label),
        "%%COUNT%%": str(content.yaml.get("total_authors") or len(authors)),
        "%%HEADER_SUB%%": _html_escape(header_sub),
        "%%SUMMARY_ITEMS%%": _summary_items(content),
        "%%WARNING_BANNER%%": _warning_banner(content),
        "%%READING_SECTION%%": _reading_section(content),
        "%%FOOTER%%": _html_escape(f"travel-planning · Stage 2 similarity · создан {created}"),
        "%%LEGEND%%": _html_escape(
            "Категории сходства (RU = EN из исходных артефактов): "
            + taxonomy.legend("author_category")),
        "%%HAS_PRACTICAL%%": "true" if has_practical else "false",
        "%%COMP_NAMES%%": _json.dumps(_COMP_LABELS_RU, ensure_ascii=False),
        "%%CAT_LABELS%%": _json.dumps(
            {_CAT_CSS[k]: taxonomy.label("author_category", k)
             for k in CATEGORIES},
            ensure_ascii=False),
        "%%COMP_WEIGHTS%%": _json.dumps(list(weights)),
        "%%DATA%%": data,
    }
    html = template
    for token, value in replacements.items():
        html = html.replace(token, value)

    Path(output_path).write_text(html, encoding="utf-8")
    return str(output_path)


# ---------------------------------------------------------------------------
# Enrich практикой из 1_dr_reports.md (только для HTML)
# ---------------------------------------------------------------------------


def enrich_with_practical(content: Stage2Content, dr_path: str | Path) -> bool:
    """Заполнить `Author.practical` из DR-карточек Stage 1. Матчинг по URL.

    Возвращает True, если хоть один автор обогащён (→ показать таб «Практика»).
    Поля DR: 14 (POI), 15 (hidden gems), 18 (жалобы/предупреждения),
    20 (фото-интересы). Graceful: при отсутствии/ошибке файла → False.
    """
    dr_path = Path(dr_path)
    if not dr_path.exists():
        return False
    try:
        if __package__ in (None, ""):
            from export.stages import stage1 as _stage1  # type: ignore[no-redef]
            from export import parser as _parser          # type: ignore[no-redef]
        else:
            from . import stage1 as _stage1
            from .. import parser as _parser
        dr_parsed = _parser.parse_stage_file(dr_path)
        dr_extracted = _stage1.extract_content(dr_parsed)
    except Exception:
        return False

    # url(norm) → practical dict из DR-карточек.
    practical_by_url: dict[str, dict] = {}
    for region in dr_extracted.get("regions") or []:
        for card in region.cards:
            url, _title = _stage1._extract_url_and_title(_stage1._fv(card.fields, 1))
            if not url:
                continue
            prac = {
                "poi": _clean_field(_stage1._fv(card.fields, 14)),
                "gems": _clean_field(_stage1._fv(card.fields, 15)),
                "warnings": _clean_field(_stage1._fv(card.fields, 18)),
                "photo": _clean_field(_stage1._fv(card.fields, 20)),
            }
            prac = {k: v for k, v in prac.items() if v}
            if prac:
                practical_by_url[_norm_url(url)] = prac

    if not practical_by_url:
        return False

    enriched = 0
    for a in content.all_detailed():
        if not a.url:
            continue
        prac = practical_by_url.get(_norm_url(a.url))
        if prac:
            a.practical = prac
            enriched += 1
    return enriched > 0


def _clean_field(v: str | None) -> str | None:
    """Срезать пустые/«не указано» значения DR-поля."""
    if not v or not v.strip():
        return None
    if re.match(r"^\s*(?:—|–|-|не\s+указан|n/a|none)\s*$", v.strip(), re.IGNORECASE):
        return None
    return v.strip()


# ---------------------------------------------------------------------------
# Renderer entry points + регистрация
# ---------------------------------------------------------------------------


def render_stage2_pdf(parsed: dict, *, recipient: str = "self",
                      output_path: str | Path, **_kw: Any) -> "_renderer.RenderRequest":
    """Entry-point PDF: parsed 2_similarity → scoring-витрина."""
    content = extract_content(
        parsed, input_path=[_kw.get("source_file"), output_path])
    pdf_path = build_pdf(content, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage": "2_similarity",
            "trip_id": content.trip_id,
            "recipient": recipient,
            "authors_count": len(content.full_table),
            "high_count": len(content.high),
            "outlier_count": len(content.outlier),
        },
        metadata={
            "trip_id": content.trip_id,
            "stage": parsed.get("stage"),
            "recipient": recipient,
            "font_family": getattr(pdf_lib, "_ACTIVE_FAMILY", None),
        },
    )


def render_stage2_html(parsed: dict, *, recipient: str = "self",
                       output_path: str | Path, source_file: str | Path | None = None,
                       dr_path: str | Path | None = None,
                       **_kw: Any) -> "_renderer.RenderRequest":
    """Entry-point HTML: parsed 2_similarity → интерактивный lookup.

    DR-путь резолвится автоматически рядом с source_file (`1_dr_reports.md`),
    если не передан явно.
    """
    content = extract_content(parsed, input_path=[source_file, output_path])
    if dr_path is None and source_file is not None:
        cand = Path(source_file).parent / "1_dr_reports.md"
        if cand.exists():
            dr_path = cand
    html_path = build_html(content, output_path, recipient=recipient, dr_path=dr_path)
    return _renderer.RenderRequest(
        format="html",
        output_path=html_path,
        content={
            "stage": "2_similarity",
            "trip_id": content.trip_id,
            "recipient": recipient,
            "authors_count": len(content.full_table),
            "practical_enriched": bool(dr_path),
        },
        metadata={
            "trip_id": content.trip_id,
            "stage": parsed.get("stage"),
            "recipient": recipient,
        },
    )


_renderer.register_renderer("2_similarity", "pdf", render_stage2_pdf)
_renderer.register_renderer("2_stage", "pdf", render_stage2_pdf)
_renderer.register_renderer("2_similarity", "html", render_stage2_html)
_renderer.register_renderer("2_stage", "html", render_stage2_html)

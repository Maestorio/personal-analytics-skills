"""stage3.py — Stage 3 export (POI aggregation): DOCX (primary) + PDF (secondary).

**Контракт формата** артефакта (6 POI-категорий, теги, `Комментарий пользователя`,
YAML) — канон `references/stage3/stage3-output-spec.md`; сверка —
`tests/test_format_contract.py`.

DOCX = operative-документ для пользователя: заполняет теги регионов
       (обязательно / можно / не интересно) и комментарии на каждый POI.
       Anketa-style checkbox-маркеры, internal bookmark-навигация (mini-TOC,
       coverage-таблица, combined_with chip-links).

PDF  = read-only витрина: всё как в DOCX, но пустые поля (тег / комментарий)
       скрываются; навигация через outline (Navigation Pane) и named
       destinations.

Extractor парсит:
  - `3_poi_aggregation.md` (основной артефакт): регионы, POI cards, cluster
    headers, Контекст, Warnings, Распределение, Non-mainstream highlights.
  - Опционально `1_dr_reports.md` (рядом в trips/{trip_id}/): lookup
    `cXX` → {author_name, url, year} для обогащения атрибуции выдержек.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Dual-mode импорт: работает и при `python stage3.py` (без пакета),
# и при `from .stages import stage3` (через package).
if __package__ in (None, ""):
    _PARENT = Path(__file__).resolve().parents[1]
    if str(_PARENT) not in sys.path:
        sys.path.insert(0, str(_PARENT))
    import pdf_lib as P                              # type: ignore[no-redef]
    import docx_lib as D                             # type: ignore[no-redef]
    import style as S                                # type: ignore[no-redef]
    import renderer as _renderer                     # type: ignore[no-redef]
    import cover_common as CC                         # type: ignore[no-redef]
    import travelers as _travelers                    # type: ignore[no-redef]
    import html_lib                                  # type: ignore[no-redef]
    import file_naming                               # type: ignore[no-redef]  # noqa: F401
    from parser import parse_stage_file              # type: ignore[no-redef]  # noqa: F401
else:
    from .. import pdf_lib as P
    from .. import docx_lib as D
    from .. import style as S
    from .. import renderer as _renderer
    from .. import cover_common as CC
    from .. import travelers as _travelers
    from .. import html_lib
    from .. import file_naming  # noqa: F401
    from ..parser import parse_stage_file  # noqa: F401

# taxonomy — словарь таксонов (scripts/taxonomy.py, на уровень выше export/).
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import taxonomy


# ---------------------------------------------------------------------------
# Двуязычная таксономия: парсер принимает EN+RU ярлыки, внутри — EN-форма,
# рендер печатает русские ярлыки через taxonomy.label().
# ---------------------------------------------------------------------------

def _canon_poi_cat(text: str) -> str:
    """Ярлык категории POI (EN/RU) → канонический space-EN ('STRONG CONFIRMED').

    Нерезолвимый/пустой текст возвращается как есть (как было до двуязычия —
    `CATEGORY_COLORS`/`CATEGORY_SHORT` ждут именно space-EN-ключи)."""
    if not text:
        return text
    key = taxonomy.canon("poi_category", text)
    return taxonomy.label("poi_category", key, "en") if key else text.strip()


def _canon_author_cat(text: str) -> str:
    """Ярлык категории автора (EN/RU) → канонический EN-ключ ('HIGH' …)."""
    return taxonomy.canon("author_category", text) or (text or "").strip()


def _pc(cat: str) -> str:
    """Полный русский ярлык категории POI (для подписей/таблиц)."""
    key = taxonomy.canon("poi_category", cat)
    return taxonomy.label("poi_category", key) if key else cat


def _pc_badge(cat: str) -> str:
    """Русский badge-ярлык категории POI (короткая форма)."""
    key = taxonomy.canon("poi_category", cat)
    return taxonomy.label("poi_category_badge", key) if key else cat


def _ac(key: str) -> str:
    """Русский ярлык категории автора по каноническому EN-ключу."""
    return taxonomy.label("author_category", key)


# Канонический порядок 6 категорий POI (для badge-заголовков coverage-таблицы).
_POI_CAT_ORDER = [
    "STRONG_CONFIRMED", "WEAK_CONFIRMED", "HIDDEN_GEM",
    "CONTESTED", "RED_FLAG", "LOW_SIGNAL",
]


# ---------------------------------------------------------------------------
# Регулярки парсера Stage 3 md
# ---------------------------------------------------------------------------

# H3 регион: `### Сием-Рип и Ангкор — 19 POI · **тег:** обязательно`
_REGION_HEADER_RE = re.compile(
    r"^###\s+(.+?)\s+—\s+(\d+)\s+POI(?:\s*·\s*\*\*тег:\*\*\s*(.+?))?\s*$",
    re.MULTILINE,
)

# Комментарий к региону (что ещё хочется посмотреть) — строка под заголовком
# региона: `**Комментарий к региону:** текст`. Метка намеренно НЕ содержит
# «Комментарий пользователя»: check_format считает такие строки как число POI.
# Группа 1 — префикс (для хирургии edit-слоя), группа 2 — значение.
_REGION_COMMENT_RE = re.compile(
    r"^([ \t]*\*\*Комментарий к региону:\*\*[ \t]*)(.*?)[ \t]*$",
    re.MULTILINE,
)

# H4 cluster header: `#### Cluster: Водопады плато Боловен (день-тур) (5 POI) — LOW SIGNAL`
_CLUSTER_HEADER_RE = re.compile(
    r"^####\s+Cluster:\s+(.+?)\s+\((\d+)\s+POI\)(?:\s+—\s+(.+))?\s*$",
    re.MULTILINE,
)

# POI header: `#1 **Ангкор-Ват** (Angkor Wat) — WEAK CONFIRMED`. Допускаем
# ведущие пробелы: при ручной правке md markdown-редактор иногда делает
# отступ (`   #4 …`), и якорь `^#` пропускал такие POI целиком (терялись из
# экспорта, а их тело прилипало к предыдущему POI — ломалась атрибуция trap).
# POI-заголовок: `#N **Имя** (English) — категория`. Скобки с англ./локальным
# именем ОПЦИОНАЛЬНЫ (методика: «английский и местный вариант ЕСЛИ ЕСТЬ») и
# содержимое **жадное** — переживает вложенные скобки в значении
# (`#15 **Музей Сучжоу** (Suzhou Museum (I.M. Pei)) — HIDDEN GEM`) и их полное
# отсутствие (`#11 **Центр Пекина (городская среда)** — LOW SIGNAL`). Раньше
# скобки были обязательны и не-жадны → такие POI молча выпадали из парса.
_POI_HEADER_RE = re.compile(
    r"^[ \t]*#(\d+)\s+\*\*(.+?)\*\*(?:\s+\((.+)\))?\s+—\s+(.+?)\s*$",
    re.MULTILINE,
)

# Поля POI 1-6: `1. Регион: ...`. Номер может быть многозначным (10+) и со
# съехавшим отступом (`    1. Комментарий`) — при ручной правке md редактор
# иногда и перенумеровывает (5.→17.), и делает поле вложенным списком. `\d+`
# + опц. ведущие пробелы это переживают; поля всё равно кладутся по лейблу
# (_classify_field), так что номер несущественен. Excerpt-буллеты (`- …`) и
# маркеры (`**…**`) под эту строку не попадают — там не цифра.
_FIELD_RE = re.compile(r"^[ \t]*(\d+)\.\s+(.+?)$", re.MULTILINE)

# Ярлыки категорий автора — двуязычны (taxonomy.pattern); числа захватываются
# позиционно, от языка не зависят.
_AC_PAT = taxonomy.pattern("author_category")

# Подсчёты поля 2: канон Фазы 2b — «ВЫСОКАЯ: N (рекоменд. X · нейтр. Y · ...)»;
# легаси-форма «HIGH упомянули: N (…)» принимается тем же выражением (слово
# «упомянули» опционально). Якорь, отличающий поле 2 от поля 3, — `(рекоменд.`.
_HIGH_COUNTS_RE = re.compile(
    rf"{_AC_PAT}\s*(?:упомянули)?\s*:\s*(\d+)\s*"
    r"\(\s*рекоменд\.\s*(\d+)"
    r"(?:\s*·\s*нейтр\.\s*(\d+))?"
    r"(?:\s*·\s*критик\.\s*(\d+))?"
    r"(?:\s*·\s*жалеют\s+о\s+посещении\s*(\d+))?"
    r"(?:\s*·\s*жалеют\s+что\s+пропустили\s*(\d+))?",
    re.IGNORECASE,
)

# Поле 3: «ОСОБЫЙ СИГНАЛ / СРЕДНЯЯ / НИЗКАЯ: X / Y / Z» (канон 2b) либо
# легаси «OUTLIER / MEDIUM / LOW упомянули: X / Y / Z».
_OML_COUNTS_RE = re.compile(
    rf"{_AC_PAT}\s*/\s*{_AC_PAT}\s*/\s*{_AC_PAT}\s*(?:упомянули)?\s*:\s*"
    r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)",
    re.IGNORECASE,
)

# Классификация полей-счётчиков по лейбл-префиксу (двуязычно). Поле 3 —
# префиксное надмножество поля 2, поэтому проверяется первым.
_OML_FIELD_RE = re.compile(rf"^{_AC_PAT}\s*/\s*{_AC_PAT}\s*/\s*{_AC_PAT}", re.IGNORECASE)
_HIGH_FIELD_RE = re.compile(rf"^({_AC_PAT})\b", re.IGNORECASE)

# Combined with: `**Combined with:** Кох-Кер — c03 явно объехала оба ...`
_COMBINED_RE = re.compile(
    r"^\*\*Combined\s+with:\*\*\s+(.+?)(?:\s+—\s+(.+))?$",
    re.MULTILINE,
)

# Cluster: `**Cluster:** Водопады плато Боловен` (None для POI без cluster)
_CLUSTER_FIELD_RE = re.compile(
    r"^\*\*Cluster:\*\*\s+(.+?)$",
    re.MULTILINE,
)

# Iconic status: `**Iconic status:** world_iconic — описание`
_ICONIC_STATUS_RE = re.compile(
    r"^\*\*Iconic\s+status:\*\*\s+(\w+?)(?:_iconic)?(?:\s+—\s+(.+))?$",
    re.MULTILINE | re.IGNORECASE,
)

# Trap archetype. Spec (§6.10 Stage 3) предписывает русскую человеко-метку
# `**⚠ Tourist-trap archetype:** {archetype} — {reasoning}`; принимаем и её,
# и старую `**Trap archetype:**`. Опц. `⚠`, опц. `Tourist-`, ведущие пробелы
# (строка в md идёт с отступом под полем 5).
_TRAP_RE = re.compile(
    r"^[ \t]*\*\*(?:⚠\s*)?(?:Tourist[-\s])?Trap\s+archetype:\*\*\s+"
    r"(.+?)(?:\s+—\s+(.+))?$",
    re.MULTILINE | re.IGNORECASE,
)

# Iconic exception: `**Iconic exception:** present — {reason}`
_EXCEPTION_RE = re.compile(
    r"^\*\*Iconic\s+exception:\*\*\s+(.+?)$",
    re.MULTILINE | re.IGNORECASE,
)

# Режим категоризации в blockquote: `> **Режим категоризации региона:** abundant (HIGH-авторов: 3) — ...`
_REGIME_RE = re.compile(
    r"\*\*Режим\s+категоризации(?:\s+региона)?:\*\*\s+(\w+)\s*"
    r"\(HIGH-авторов?:\s*(\d+)\)"
)

# Выдержка: bullet-строка вида `- {лейбл автора} ({TIER}): {текст}`. Якорь —
# `({TIER}):`; всё слева от него — лейбл автора, который бывает в трёх формах
# (`cXX Имя`, `Имя #NN`, голое `Имя`) — их разбирает _parse_excerpt_label.
# Раньше регэксп жёстко требовал `cXX Имя` в начале и молча давал ноль
# совпадений на форме `Имя #NN` (→ в экспорте пропадали все авторы под POI).
_EXCERPT_RE = re.compile(
    rf"^\s*[-•]\s+(.*?)\s*\(({_AC_PAT})\):\s+(.+?)$",
    re.MULTILINE,
)

# Stage 1 card header. Канон — `## КАРТОЧКА N`, но реальные DR-файлы дают и
# `**КАРТОЧКА N**` (bold), и `### Карточка N — tonality: critical`. Принимаем
# bold/heading + регистр любой (раньше жёсткое `### Карточка` давало пустой
# lookup → у авторов не было URL/года).
_STAGE1_CARD_RE = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|\*\*[ \t]*)?"
    r"(?:КАРТОЧКА|Карточка|Card|Отчёт|Отчет|Report)[ \t]+0*(\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# Stage 1 поля — LABEL-based, не по номеру. Реальные DR-карточки нумеруют
# ВСЕ поля как `1.` и НЕ выделяют лейбл жирным (`1. URL и название: <url>`,
# `1. Автор: …`), тогда как старые фикстуры дают `3. **Автор:**`. Поэтому
# матчим по лейблу с любым ведущим номером и опциональным bold/двоеточием;
# URL может быть в угловых скобках. Старое жёсткое `^3\.\s+\*\*Автор:\*\*`
# давало пустой lookup на реальных файлах.
#
# Field 1 — URL. Лейбл толерантен к словам после `URL` до двоеточия:
# `URL и название:` И `URL и название отчёта:` (реальные DR расходятся) —
# `(?:\s+[^\s:<]+)*` съедает любые слова-токены до `:` / `<`, не трогая сам URL.
_STAGE1_FIELD1_RE = re.compile(
    r"^\s*\d+\.\s*\*{0,2}\s*URL(?:\s+[^\s:<]+)*\s*:?\s*\*{0,2}\s*"
    r"<?(https?://[^\s>]+)>?"
    r"(?:\s*[—–-]\s*«?(.+?)»?\s*)?$",
    re.MULTILINE | re.IGNORECASE,
)

# Field 3 — Автор. Лейбл бывает `Автор:` И `Имя или ник автора:` (и просто
# `Ник:`) — матчим любую из форм, значение после двоеточия.
_STAGE1_FIELD3_RE = re.compile(
    r"^\s*\d+\.\s*\*{0,2}\s*(?:Имя[^:<\n]*?автор\w*|Автор\w*|Ник\w*)"
    r"\s*:?\s*\*{0,2}\s*(.+?)\s*\*{0,2}\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Field 4 — Дата публикации (первое 4-значное число в значении).
_STAGE1_FIELD4_RE = re.compile(
    r"^\s*\d+\.\s*\*{0,2}\s*Дата\s+публикации\s*:?\s*\*{0,2}.*?(\d{4})",
    re.MULTILINE | re.IGNORECASE,
)

# Field 1 — лейбл URL + захват ВСЕГО значения строки (для мульти-URL парсинга).
# `_STAGE1_FIELD1_RE` ждал одну ссылку `<url> — «title»` и проваливался на
# поле с 2+ отчётами (`<url1> (Пекин) + <url2> (Сучжоу) — …`) → автор без линка.
_STAGE1_FIELD1_LABEL_RE = re.compile(
    r"^\s*\d+\.\s*\*{0,2}\s*URL(?:\s+[^\s:<]+)*\s*:?\s*\*{0,2}\s*(.+)$",
    re.MULTILINE | re.IGNORECASE,
)
# URL + опциональная метка-аннотация сразу после него: `<url> (Пекин, ВКС)`.
_URL_WITH_LABEL_RE = re.compile(r"<?(https?://[^\s>)]+)>?\s*(?:\(([^)]*)\))?")
# Название отчёта — ПЕРВОЕ «…» в значении поля (= заголовок url1). Берём первое,
# а не последнее: у мульти-URL бывает «title1» и «title2» (c14) либо «title» +
# поясняющая проза с «цитатой» (c25) — первое «…» надёжно даёт главный заголовок.
_REPORT_TITLE_RE = re.compile(r"«([^»]*)»")


def _url_domain(url: str) -> str:
    """netloc без `www.` — текст ссылки-домена."""
    from urllib.parse import urlparse
    try:
        netloc = urlparse(url).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return url


def _parse_report_urls(value: str) -> tuple[list[dict], str | None]:
    """Разобрать значение поля 1 в (список ссылок, название отчёта).

    Поддерживает мульти-URL: `<url1> (Пекин) + <url2> (Сучжоу) — …`,
    `<url1> и <url2> — «Title»`, `<url> — «Title»`. Каждая ссылка —
    `{"url": ..., "label": <аннотация в скобках> | None}`. Название —
    трейлинговое «…» (если есть; у мульти-URL с метками его обычно нет).
    """
    value = value.strip()
    mt = _REPORT_TITLE_RE.search(value)
    title = mt.group(1).strip() if mt else None
    links: list[dict] = []
    for m in _URL_WITH_LABEL_RE.finditer(value):
        url = m.group(1).rstrip(">,.;")
        label = (m.group(2) or "").strip() or None
        links.append({"url": url, "label": label})
    return links, title


# Stage 0 region H3 — пока не используется builder'ом напрямую (Stage 0
# raw-описания слишком длинны для presentation; polish может его читать
# как context, но в builder приходят уже polished-маркеры).
_STAGE0_REGION_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_STAGE0_TAIL_RE = re.compile(r"\s*—\s*(?:RESERVE|CORE|MUST|NICHE|BORDERLINE).*$")

# Polish-маркеры регионального уровня. Polish может вставить ИХ в любое
# место body (типично — внутри секции «Полная агрегация POI» рядом с
# regional блоком, но parser ищет глобально).
#   [[регион: <имя> | описание: <текст 1-2 предложения>]]
#   [[регион: <имя> | авторы: <текст 1-3 предложения>]]
#   [[регион: <имя> | english: <English-имя для search query>]]
_REGION_MARKER_RE = re.compile(
    r"\[\[\s*регион:\s*(.+?)\s*\|\s*(описание|авторы|english)\s*:\s*(.+?)\s*\]\]",
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Excerpt:
    """Одна выдержка из POI-карточки."""
    author_id: str       # `c02`
    author_name: str     # `Дария` — из самой строки выдержки (КАК ЕСТЬ,
                          # без auto-promote из Stage 1 — там автор-имя
                          # может быть многословным «анонимный пользователь
                          # Tripadvisor (из Сингапура)»; в карточках нам
                          # нужна компактность)
    similarity: str      # `HIGH` / `OUTLIER` / `MEDIUM` / `LOW`
    text: str            # сама цитата / описание
    # Обогащение из Stage 1 lookup (необязательное):
    url: str | None = None
    year: int | None = None
    report_title: str | None = None   # название отчёта (поле 1, в «...»)
    report_urls: list | None = None   # все ссылки поля 1: [{url, label}, ...]

    @property
    def tone(self) -> str:
        """Эвристика тона по содержимому выдержки.

        Поскольку Stage 3 md не маркирует тон явно для каждой выдержки
        (только агрегированные counts в полях 2-3), используем простой
        keyword-based scorer.
        """
        t = self.text.lower()
        neg_markers = (
            "критикует", "разочарован", "boring", "scam", "не реко",
            "плохо", "ужасн", "ghost town", "вырубк", "деградац",
            "переоценен", "overrated", "не стоит", "детск",
        )
        pos_markers = (
            "рекомендует", "сильно реко", "лучшее", "must", "обязательно",
            "сказочн", "волшебн", "highlight", "favorite", "favourite",
            "хорош", "впечатл", "красив", "true masterpiece",
        )
        for m in neg_markers:
            if m in t:
                return "neg"
        for m in pos_markers:
            if m in t:
                return "pos"
        return "neu"


@dataclass
class POI:
    num: int
    name_ru: str
    name_local: str
    category: str
    region: str
    high_total: int = 0
    high_recommend: int = 0
    high_neutral: int = 0
    high_negative: int = 0
    high_regret_visited: int = 0
    high_regret_missed: int = 0
    outlier_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    excerpts: list[Excerpt] = field(default_factory=list)
    characteristics: str = ""
    user_comment: str = ""
    combined_with: list[dict] = field(default_factory=list)
    cluster_name: str | None = None
    trap_archetype: dict | None = None
    iconic_status: str | None = None
    iconic_exception: str | None = None


@dataclass
class Cluster:
    name: str
    member_count: int
    aggregate_category: str
    note: str
    member_nums: list[int] = field(default_factory=list)


@dataclass
class Region:
    name: str
    poi_count: int
    tag: str | None
    mode: str                  # «abundant (HIGH-авторов: 3)»
    description: str           # из Stage 3 md (обычно placeholder «недоступно»)
    polished_description: str | None = None       # из polish-маркера
    polished_authors_summary: str | None = None   # из polish-маркера
    user_comment: str | None = None               # `**Комментарий к региону:**`
                                                   # (что ещё хочется посмотреть)
    english_name: str | None = None               # из polish-маркера, для
                                                   # search query Google Images
                                                   # (например «Siem Reap»)
    clusters: list[Cluster] = field(default_factory=list)
    pois: list[POI] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Author lookup из 1_dr_reports.md
# ---------------------------------------------------------------------------

def load_region_descriptions(stage0_path: Path | None) -> dict[str, str]:
    """Прочитать `0_scope_*.md` и собрать map region_name → краткое описание.

    Для каждой H3-секции Stage 0 ищем строку, которая начинается на
    «Принципиально:» — это самое информативное предложение per регион
    («что делает регион уникальным для путешественника»). НЕ берём
    «Состав:» (это перечисление POI, и так есть в карточках ниже),
    НЕ берём логистику/сезон/density (служебная мета).

    Результат обрезается до 240 символов — короткий passthrough в PDF/DOCX
    region header.

    Используется как fallback если polish НЕ сгенерировал
    `[[регион: ... | описание: ...]]` маркер.
    """
    if stage0_path is None or not stage0_path.exists():
        return {}
    try:
        text = stage0_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    out: dict[str, str] = {}
    matches = list(_STAGE0_REGION_RE.finditer(text))
    for idx, m in enumerate(matches):
        raw_name = m.group(1).strip()
        name = _STAGE0_TAIL_RE.sub("", raw_name).strip()
        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        h2_stop = re.search(r"^##\s", body, re.MULTILINE)
        if h2_stop:
            body = body[:h2_stop.start()].strip()

        # Ищем строку «Принципиально: ...» (уникальная характеристика
        # региона для путешественника, не дублирующая POI карточки).
        # Два формата Stage 0:
        #   «Принципиально: ...»            (Камбоджа)
        #   «- **Что принципиально:** ...»  (Корея — bullet + bold)
        principal: str | None = None
        for line in body.splitlines():
            ls = line.strip()
            # снимаем bullet и bold-обёртку
            ls_clean = re.sub(r"^[-*]\s*", "", ls)
            ls_clean = ls_clean.replace("**", "")
            m = re.match(r"(?:что\s+)?принципиально:\s*(.+)", ls_clean,
                         re.IGNORECASE)
            if m:
                principal = m.group(1).strip()
                break
        if principal:
            if len(principal) > 240:
                principal = principal[:237].rstrip() + "…"
            out.setdefault(name, principal)
    return out


def load_author_lookup(stage1_path: Path | None) -> dict[str, dict]:
    """Прочитать соседний 1_dr_reports.md и собрать dict cNN → {name, url, year}.

    Если файл не найден/нечитаем — возвращает пустой dict. Это допустимо,
    Stage 3 рендер работает и без обогащения (атрибуция остаётся как
    `cNN Имя (HIGH)` без url/year).
    """
    if stage1_path is None or not stage1_path.exists():
        return {}
    try:
        text = stage1_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    lookup: dict[str, dict] = {}
    # Идём по `### Карточка N` блокам, парсим следом fields 1/3/4.
    cards = list(_STAGE1_CARD_RE.finditer(text))
    for idx, m in enumerate(cards):
        num = int(m.group(1))
        body_start = m.end()
        body_end = cards[idx + 1].start() if idx + 1 < len(cards) else len(text)
        body = text[body_start:body_end]

        key = f"c{num:02d}"
        entry: dict[str, Any] = {}

        m1 = _STAGE1_FIELD1_LABEL_RE.search(body)
        if m1:
            links, title = _parse_report_urls(m1.group(1))
            if links:
                entry["report_urls"] = links
                entry["url"] = links[0]["url"]  # backward-compat (один url)
            if title:
                entry["report_title"] = title

        m3 = _STAGE1_FIELD3_RE.search(body)
        if m3:
            entry["author_name"] = m3.group(1).strip()

        m4 = _STAGE1_FIELD4_RE.search(body)
        if m4:
            try:
                entry["year"] = int(m4.group(1))
            except ValueError:
                pass

        if entry:
            lookup[key] = entry
    return lookup


# Встроенный реестр авторов в самом Stage 3 md (self-contained экспорт «1 файл»).
# Формат: секция `## Источники (реестр авторов)` + строки
#   `- cNN | имя | год | <url-поле как в Stage 1 поле 1>`
# url-поле парсится тем же `_parse_report_urls` (мульти-URL + метки + «название»).
_REGISTRY_HEADER_RE = re.compile(
    r"^##\s+Источники\s*\(реестр\s+авторов\)\s*$", re.MULTILINE | re.IGNORECASE)
_REGISTRY_LINE_RE = re.compile(
    r"^\s*[-*]\s*(c\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*(.+?)\s*$",
    re.MULTILINE)


def load_author_registry(text: str) -> dict[str, dict]:
    """Прочитать встроенный в Stage 3 md реестр авторов → dict cNN → {name,
    url, report_urls, report_title, year}. Тот же контракт, что
    `load_author_lookup`, но источник — сам файл (Stage 1 не нужен).

    Возвращает пустой dict, если секции реестра нет (старый файл → fallback
    на Stage 1 lookup в `extract_content`).
    """
    m = _REGISTRY_HEADER_RE.search(text)
    if not m:
        return {}
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    section = rest[:nxt.start()] if nxt else rest
    lookup: dict[str, dict] = {}
    for lm in _REGISTRY_LINE_RE.finditer(section):
        cid, name, year, urlfield = lm.groups()
        entry: dict[str, Any] = {}
        if name.strip():
            entry["author_name"] = name.strip()
        if year.strip().isdigit():
            entry["year"] = int(year.strip())
        links, title = _parse_report_urls(urlfield)
        if links:
            entry["report_urls"] = links
            entry["url"] = links[0]["url"]
        if title:
            entry["report_title"] = title
        if entry:
            lookup[cid] = entry
    return lookup


# ---------------------------------------------------------------------------
# Извлечение полей внутри POI body
# ---------------------------------------------------------------------------

def _split_poi_body(region_body: str) -> list[tuple[int, str]]:
    """Разделить body региона на POI-блоки.

    Возвращает [(start_offset, end_offset_or_-1), ...] — позиции POI header'ов.
    Затем caller сам нарезает body[start:end] для каждого POI.
    """
    headers = list(_POI_HEADER_RE.finditer(region_body))
    result = []
    for idx, m in enumerate(headers):
        start = m.start()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(region_body)
        result.append((start, end))
    return result


def _parse_fields(body: str) -> list[str]:
    """Разобрать пронумерованные поля POI в **упорядоченный список** их текстов.

    Номер поля НЕ используется как ключ: реальные md нумеруют все поля как `1.`
    (стандартный markdown — авторендер сам считает 1,2,3…), и dict[int,str]
    коллапсировал все `1.` в одну запись → в карточке оставалось только
    последнее поле («Комментарий»), а выдержки/счётчики/характеристики
    пропадали. Поля классифицируются по лейблу (`_classify_field`), так что
    порядок сохраняем, номер игнорируем.
    """
    fields: list[str] = []
    started = False
    buf: list[str] = []
    for line in body.splitlines():
        m = _FIELD_RE.match(line)
        if m:
            if started:
                fields.append("\n".join(buf).strip())
            started = True
            buf = [m.group(2).strip()]
        elif started:
            # Продолжение текущего поля (например, выдержки многострочно в поле 4).
            buf.append(line)
    if started:
        fields.append("\n".join(buf).strip())
    return fields


def _parse_counts_field2(text: str) -> dict:
    """Распарсить поле 2 `Регион: ...` (для region — string), либо
    `HIGH упомянули: ...` (для counts)."""
    out: dict = {"high_total": 0, "high_recommend": 0, "high_neutral": 0,
                 "high_negative": 0, "high_regret_visited": 0,
                 "high_regret_missed": 0}
    m = _HIGH_COUNTS_RE.search(text)
    if m:
        out["high_total"] = int(m.group(1))
        out["high_recommend"] = int(m.group(2) or 0)
        out["high_neutral"] = int(m.group(3) or 0)
        out["high_negative"] = int(m.group(4) or 0)
        out["high_regret_visited"] = int(m.group(5) or 0)
        out["high_regret_missed"] = int(m.group(6) or 0)
    return out


def _parse_counts_field3(text: str) -> tuple[int, int, int]:
    """Поле 3: OUTLIER / MEDIUM / LOW."""
    m = _OML_COUNTS_RE.search(text)
    if not m:
        return 0, 0, 0
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _parse_excerpt_label(label: str) -> tuple[str, str]:
    """Из лейбла выдержки (всё слева от `(TIER):`) извлечь (author_id, name).

    Принимает три исторические формы:
      - `c44 Пашик`         → ('c44', 'Пашик')
      - `Пашик #44`         → ('c44', 'Пашик')
      - `Walk My World #10` → ('c10', 'Walk My World')
      - `Пашик`             → ('', 'Пашик')   (id неизвестен)
    Номер карточки нормализуется в `cNN` — это ключ джойна с lookup из
    Stage 1 (`load_author_lookup` строит ключи `c{num:02d}`).
    """
    s = (label or "").strip()
    m = re.match(r"^(c\d+)\s+(.+)$", s)            # cNN Имя
    if m:
        return m.group(1), m.group(2).strip()
    m = re.match(r"^(.+?)\s+#(\d+)\s*$", s)         # Имя ... #NN
    if m:
        return f"c{int(m.group(2)):02d}", m.group(1).strip()
    m = re.match(r"^#(\d+)\s+(.+)$", s)             # #NN Имя
    if m:
        return f"c{int(m.group(1)):02d}", m.group(2).strip()
    return "", s


def _parse_excerpts(field4_text: str, lookup: dict[str, dict]) -> list[Excerpt]:
    """Поле 4 — список выдержек. Обогащаем из lookup, если есть."""
    out: list[Excerpt] = []
    for m in _EXCERPT_RE.finditer(field4_text):
        author_label = m.group(1).strip()
        similarity = _canon_author_cat(m.group(2))
        text = m.group(3).strip()
        author_id, author_name = _parse_excerpt_label(author_label)
        ex = Excerpt(
            author_id=author_id,
            author_name=author_name,
            similarity=similarity,
            text=text,
        )
        info = lookup.get(author_id)
        if info:
            ex.url = info.get("url")
            ex.year = info.get("year")
            ex.report_title = info.get("report_title")
            ex.report_urls = info.get("report_urls")
            # NB: НЕ перетираем `ex.author_name` из Stage 1 даже если
            # имя там полнее — Stage 1 часто имеет многословные описания
            # авторов («анонимный пользователь Tripadvisor (заявил себя
            # как путешественник из Сингапура)»), которые ломают
            # компактность POI-карточек. Stage 3 даёт уже подходящий
            # короткий вариант.
        out.append(ex)
    return out


def _parse_extra_flags(body: str) -> dict:
    """Парсит опциональные блоки **Combined with:**, **Cluster:**,
    **Iconic status:**, **Trap archetype:**, **Iconic exception:**."""
    extra: dict = {
        "combined_with": [],
        "cluster_name": None,
        "iconic_status": None,
        "trap_archetype": None,
        "iconic_exception": None,
    }
    for m in _COMBINED_RE.finditer(body):
        name = m.group(1).strip()
        why = (m.group(2) or "").strip() or None
        extra["combined_with"].append({"poi_name": name, "why": why})
    m = _CLUSTER_FIELD_RE.search(body)
    if m:
        val = m.group(1).strip()
        if val.lower() not in ("none", "—"):
            extra["cluster_name"] = val
    m = _ICONIC_STATUS_RE.search(body)
    if m:
        extra["iconic_status"] = m.group(1).strip().lower()
    m = _TRAP_RE.search(body)
    if m:
        extra["trap_archetype"] = {
            "archetype": m.group(1).strip(),
            "reasoning": (m.group(2) or "").strip(),
        }
    m = _EXCEPTION_RE.search(body)
    if m:
        extra["iconic_exception"] = m.group(1).strip()
    return extra


def _classify_field(text: str) -> str | None:
    """По началу текста поля определить его семантический ключ.

    Привязка к ЛЕЙБЛУ, не к номеру: при ручной правке md нумерация полей
    «съезжает» (5.→17., целый POI 30.–35.), но лейблы стабильны. Раньше
    `_build_poi` брал поля по номеру (`fields.get(5)`) и на съехавшем файле
    молча терял характеристики/выдержки/комментарий.
    """
    t = text.lstrip().lower()
    if t.startswith("регион"):
        return "region"
    if t.startswith("выдержк"):
        return "excerpts"
    if t.startswith("характеристик"):
        return "characteristics"
    if t.startswith("комментарий"):
        return "comment"
    # Счётчики (поля 2/3) — лейбл двуязычен. Поле 3 («X / Y / Z») проверяем
    # первым: его префикс — валидное поле 2.
    if _OML_FIELD_RE.match(t):
        return "oml"
    m = _HIGH_FIELD_RE.match(t)
    if m:
        # Легаси поле 3 начиналось с OUTLIER и без обязательной тройки.
        key = taxonomy.canon("author_category", m.group(1))
        return "oml" if key == "OUTLIER" else "high"
    return None


def _build_poi(
    num: int, name_ru: str, name_local: str, category: str, body: str,
    region_name: str, lookup: dict[str, dict],
) -> POI:
    fields = _parse_fields(body)
    # Перекладываем поля по лейблу (устойчиво к нумерации `1./1./1.` и съехавшей).
    by_label: dict[str, str] = {}
    for ftext in fields:
        key = _classify_field(ftext)
        if key and key not in by_label:
            by_label[key] = ftext
    field2 = by_label.get("high", "")
    field3 = by_label.get("oml", "")
    field4 = by_label.get("excerpts", "")
    field5 = by_label.get("characteristics", "")
    field6 = by_label.get("comment", "")

    counts = _parse_counts_field2(field2)
    out_, med, low = _parse_counts_field3(field3)
    excerpts = _parse_excerpts(field4, lookup)
    extras = _parse_extra_flags(body)

    # Стрипаем дублирующий label из полей 5 и 6 (md имеет вид
    # `5. Характеристики: текст` / `6. Комментарий пользователя: текст`,
    # builder сам добавляет «Характеристики:» / «Комментарий:» в карточке).
    characteristics = _strip_field_label(
        field5, ("Характеристики:",),
    )
    # Field 5 в исходнике часто содержит трейлинг-маркеры `**Combined with:**`,
    # `**Cluster:**` и т.п. (они стоят ПОСЛЕ строки 5 но ДО строки 6, поэтому
    # _parse_fields захватывает их в field5). Эти маркеры обрабатываются
    # отдельно в _parse_extra_flags и рендерятся как chips — из текста
    # характеристик их надо вырезать, иначе будет дубль.
    characteristics = _strip_trailing_markers(characteristics)
    # Заменяем internal author-id (`c04`) на читаемое имя автора —
    # авторы Stage 3 иногда пишут «По c04 ...» в характеристиках.
    characteristics = _replace_author_ids(characteristics, lookup)
    user_comment = _strip_field_label(
        field6, ("Комментарий пользователя:", "Комментарий:"),
    )
    # Поле 6 — последнее в POI; _parse_fields может захватить trailing
    # markdown-разделитель `---` (граница региона) и пустые строки.
    user_comment = re.sub(r"\s*-{3,}\s*$", "", user_comment).strip()

    return POI(
        num=num,
        name_ru=name_ru.strip(),
        name_local=name_local.strip(),
        category=category.strip(),
        region=region_name.strip(),
        high_total=counts["high_total"],
        high_recommend=counts["high_recommend"],
        high_neutral=counts["high_neutral"],
        high_negative=counts["high_negative"],
        high_regret_visited=counts["high_regret_visited"],
        high_regret_missed=counts["high_regret_missed"],
        outlier_count=out_,
        medium_count=med,
        low_count=low,
        excerpts=excerpts,
        characteristics=characteristics,
        user_comment=user_comment,
        combined_with=extras["combined_with"],
        cluster_name=extras["cluster_name"],
        iconic_status=extras["iconic_status"],
        trap_archetype=extras["trap_archetype"],
        iconic_exception=extras["iconic_exception"],
    )


def _flatten_subsection_body(subsect: dict) -> str:
    """Реконструировать text с body + всеми H4+ subsections.

    parse_sections выносит H4 в `subsections`, отделяя их от родительского
    body H3. Для парсинга POI/cluster нам нужен plain markdown текст —
    собираем его обратно.
    """
    out: list[str] = [subsect.get("body", "")]
    for sub in subsect.get("subsections", []):
        level = sub.get("level", 4)
        heading = sub.get("heading", "")
        prefix = "#" * level
        out.append(f"\n{prefix} {heading}\n")
        out.append(_flatten_subsection_body(sub))
    return "\n".join(out)


def _parse_region_block(
    region_heading_match: re.Match,
    region_body: str,
    lookup: dict[str, dict],
) -> Region:
    name = region_heading_match.group(1).strip()
    poi_count = int(region_heading_match.group(2))
    tag = region_heading_match.group(3)
    if tag:
        tag = tag.strip().strip("_")
        if not tag or tag in ("_", "—"):
            tag = None

    # Mode из blockquote
    mode = "scarce"
    m_reg = _REGIME_RE.search(region_body)
    if m_reg:
        mode = f"{m_reg.group(1).strip()} (HIGH-авторов: {m_reg.group(2)})"

    # Description — параграф «— из Stage 0: ...»
    description = ""
    for line in region_body.splitlines():
        ls = line.strip()
        if ls.startswith("— из Stage 0:"):
            description = ls[len("— из Stage 0:"):].strip()
            break

    # Комментарий к региону — ищем только в «шапке» региона (до первого
    # кластера/POI), чтобы не зацепить похожую строку в теле POI.
    head_end = len(region_body)
    for rx in (_POI_HEADER_RE, _CLUSTER_HEADER_RE):
        hm = rx.search(region_body)
        if hm:
            head_end = min(head_end, hm.start())
    cm = _REGION_COMMENT_RE.search(region_body[:head_end])
    user_comment = cm.group(2).strip() if cm and cm.group(2).strip() else None

    region = Region(
        name=name, poi_count=poi_count, tag=tag,
        mode=mode, description=description, user_comment=user_comment,
    )

    # Cluster headers
    for m in _CLUSTER_HEADER_RE.finditer(region_body):
        cl_name = m.group(1).strip()
        cl_count = int(m.group(2))
        cl_cat = _canon_poi_cat((m.group(3) or "").strip()) or "LOW SIGNAL"
        # Note: текст между cluster header и следующим POI header.
        cl_start = m.end()
        next_m = _POI_HEADER_RE.search(region_body, cl_start)
        cl_end = next_m.start() if next_m else len(region_body)
        cl_note = region_body[cl_start:cl_end].strip()
        # Уберём «Aggregated counts:» и т.п. служебные строки из note
        cl_note_lines = [
            l.strip() for l in cl_note.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        region.clusters.append(Cluster(
            name=cl_name, member_count=cl_count,
            aggregate_category=cl_cat,
            note=" ".join(cl_note_lines)[:400],
        ))

    # POIs внутри региона
    for m in _POI_HEADER_RE.finditer(region_body):
        num = int(m.group(1))
        name_ru = m.group(2)
        name_local = m.group(3) or ""   # скобки опциональны (D4)
        category = _canon_poi_cat(m.group(4))
        body_start = m.end()
        # POI body — до следующего POI header или конца региона
        next_h = _POI_HEADER_RE.search(region_body, body_start)
        body_end = next_h.start() if next_h else len(region_body)
        poi_body = region_body[body_start:body_end]
        poi = _build_poi(num, name_ru, name_local, category,
                         poi_body, region.name, lookup)
        region.pois.append(poi)
        # Маппим POI в clusters
        if poi.cluster_name:
            for cl in region.clusters:
                if cl.name == poi.cluster_name:
                    cl.member_nums.append(num)
                    break

    return region


# ---------------------------------------------------------------------------
# Распределение, warnings, контекст
# ---------------------------------------------------------------------------

# Строка таблицы распределения. Категория — двуязычна (taxonomy.pattern);
# плюс альтернатива «Всего POI / Total» (итоговая строка, пропускается).
_DISTRIBUTION_ROW_RE = re.compile(
    rf"^\|\s*({taxonomy.pattern('poi_category')}|\*\*?Всего\s+POI\*\*?|"
    r"\*\*?Total[^|]*)\s*\|\s*\*?\*?(\d+)\*?\*?",
    re.MULTILINE | re.IGNORECASE,
)


def _parse_distribution(section_body: str) -> list[tuple[str, int]]:
    """Парсит таблицу `## Распределение по категориям`.

    Принимает EN- и RU-ярлыки категорий; ключи результата — канонический
    space-EN (потребители рендера русифицируют через `_pc`)."""
    canonical = [
        "STRONG CONFIRMED", "WEAK CONFIRMED", "HIDDEN GEM",
        "CONTESTED", "RED FLAG", "LOW SIGNAL",
    ]
    raw: dict[str, int] = {}
    for m in _DISTRIBUTION_ROW_RE.finditer(section_body):
        g1 = re.sub(r"\s+", " ", m.group(1).strip())
        if "ВСЕГО" in g1.upper() or "TOTAL" in g1.upper():
            continue
        cat = _canon_poi_cat(g1)   # → space-EN
        try:
            raw[cat] = int(m.group(2))
        except ValueError:
            continue
    return [(c, raw.get(c, 0)) for c in canonical]


def _parse_warnings(section_body: str) -> list[str]:
    """Bullet list warnings секции."""
    items: list[str] = []
    for line in section_body.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "• ")):
            items.append(s[2:].strip())
    return items


# ---------------------------------------------------------------------------
# Главный extractor
# ---------------------------------------------------------------------------

def extract_content(
    parsed: dict, *,
    stage1_path: Path | None = None,
    stage0_path: Path | None = None,
    input_path: Path | None = None,
) -> dict:
    """Распарсить parsed (от parse_stage_file) Stage 3 в structured dict.

    Опциональные источники обогащения:
      - `stage1_path` (`1_dr_reports.md`) — url / year / full name авторов
        в выдержках POI;
      - `stage0_path` (`0_scope_*.md`) — описания регионов (passthrough
        в `region.description`, заменяет «недоступно» из Stage 3 md);
      - `input_path` — путь к самому артефакту, для резолвера «Кто едет»
        (профиль/`trip.yaml` относительно него, Р10).
    """
    fm = parsed.get("frontmatter") or {}
    body = parsed.get("body") or ""
    # Self-contained «1 файл»: сперва встроенный реестр авторов из самого Stage 3
    # md. Если его нет (старый файл) — fallback на Stage 1 lookup.
    lookup = load_author_registry(body) or load_author_lookup(stage1_path)
    region_descriptions = load_region_descriptions(stage0_path)

    extracted: dict = {
        "trip_id": parsed.get("trip_id"),
        "stage": parsed.get("stage", "3_poi_aggregation"),
        "title": parsed.get("title"),
        "travelers_profile": fm.get("travelers_profile"),
        "who_goes": _travelers.resolve_travelers(fm, {}, input_path),
        "total_pois": fm.get("total_pois", 0),
        "aggregation_mode": fm.get("aggregation_mode", "scarce"),
        "created": fm.get("created"),
        "distribution": [],
        "warnings": [],
        "context_lines": [],
        "regions": [],
        "non_mainstream": "",
    }

    # H2-секции
    sections = parsed.get("sections") or []
    full_agg_body = ""
    for sect in sections:
        h = sect.get("heading", "").strip()
        h_norm = h.lower()
        if "контекст" in h_norm and "стад" in h_norm:
            # `.strip("- *")` резал бы `**` и с конца строки (symmetric strip),
            # но закрывающий `**` обычно не на самом краю («**Кто/когда:**
            # пара…») — оставался непарным, ломая bold дальше по конвейеру.
            # Срезаем только ведущий буллет; жирность — задача md()/mdb().
            extracted["context_lines"] = [
                re.sub(r"^[-*]\s+", "", line.strip())
                for line in sect.get("body", "").splitlines()
                if line.strip().startswith(("- ", "* "))
                # «Итог:» дублирует таблицу «Покрытие по регионам» (строка
                # ВСЕГО несёт те же числа) — на обложке не нужен (Р11).
                and not re.match(r"^[-*]\s+\**\s*Итог\s*:", line.strip())
            ]
        elif "распределение" in h_norm:
            extracted["distribution"] = _parse_distribution(sect.get("body", ""))
        elif h_norm == "warnings" or "warning" in h_norm and len(h_norm) < 30:
            extracted["warnings"] = _parse_warnings(sect.get("body", ""))
        elif "полная агрегация" in h_norm or "агрегация poi" in h_norm:
            # Subsections внутри H2 — это H3 регионы. Каждый регион может
            # содержать H4 cluster headers как подсекции; нужно собрать
            # полный body региона (H3 own body + reconstruct всех H4+).
            for subsect in sect.get("subsections", []):
                if subsect.get("level") != 3:
                    continue
                heading = subsect.get("heading", "")
                full_body = _flatten_subsection_body(subsect)
                pseudo = f"### {heading}\n{full_body}"
                m = _REGION_HEADER_RE.search(pseudo)
                if not m:
                    continue
                region = _parse_region_block(m, full_body, lookup)
                extracted["regions"].append(region)
        elif "non-mainstream" in h_norm or "highlight" in h_norm:
            extracted["non_mainstream"] = sect.get("body", "").strip()

    # Polish-маркеры регионального уровня — ищем глобально в body
    # (polish мог положить их в любом месте). Применяем к уже собранным
    # регионам по имени.
    _apply_region_markers(extracted["regions"], body)

    # Fallback: если polish не оставил описаний, подставляем «Принципиально:»
    # строку из Stage 0 (короткая, не дублирует POI ниже).
    if region_descriptions:
        for region in extracted["regions"]:
            if not region.polished_description:
                fallback = region_descriptions.get(region.name)
                if fallback:
                    region.polished_description = fallback

    # Пост-проверка строгого формата: критичные расхождения → гейт (build
    # падает с понятным сообщением, не отдаёт кривой PDF/DOCX); мягкие →
    # warnings в stderr + extracted.
    errors, warnings = _check_parse_completeness(extracted, body)
    extracted["validation_errors"] = errors
    extracted["warnings"] = list(extracted.get("warnings") or []) + warnings
    # Хвост-ссылка на внутренний референс скилла («См. stage3-poi.md §6.5.»)
    # читателю не нужен и недоступен — срезаем из видимых warnings.
    extracted["warnings"] = [CC.strip_internal_refs(w) for w in extracted["warnings"]]
    # Сырой стем профиля в прозе контекста («пара 60–61 (`алексей_родители`)»)
    # → резолвнутое имя («Родители»); машинному идентификатору не место
    # в user-facing выводе.
    extracted["context_lines"] = [
        _travelers.replace_profile_stem(ln, fm, extracted.get("who_goes"))
        for ln in extracted["context_lines"]
    ]

    return extracted


def _check_parse_completeness(extracted: dict, raw_body: str) -> tuple[list[str], list[str]]:
    """Пост-проверка результата парсинга Stage 3.

    Возвращает `(errors, warnings)`. errors → `build_pdf`/`build_docx` падают с
    понятным сообщением (лучше, чем кривой документ без авторов/счётчиков —
    ровно та «пустые карточки»-регрессия, что ловили на Китае). warnings →
    stderr + `extracted["warnings"]`.
    """
    regions = extracted.get("regions") or []
    all_pois = [p for r in regions for p in r.pois]
    errors: list[str] = []
    warnings: list[str] = []
    if not all_pois:
        return errors, warnings

    def _mentions(p) -> int:
        return p.high_total + p.outlier_count + p.medium_count + p.low_count

    with_mentions = [p for p in all_pois if _mentions(p) > 0]
    with_excerpts = [p for p in all_pois if p.excerpts]
    total_excerpts = sum(len(p.excerpts) for p in all_pois)

    # 0 (ERROR). Число распознанных POI против YAML total_pois — потеря POI
    #    (POI-заголовок не по формату). Блокируем: иначе POI молча пропадёт.
    try:
        declared = int(extracted.get("total_pois") or 0)
    except (TypeError, ValueError):
        declared = 0
    if declared and len(all_pois) != declared:
        errors.append(
            f"распознано {len(all_pois)} POI, а в YAML total_pois={declared} — "
            "часть POI не распарсилась (POI-заголовок `#N **Имя** … — категория` "
            "не по формату). Проверь файл."
        )

    # 0b (ERROR). Полный коллапс полей: POI много, но НИ счётчиков, НИ выдержек —
    #    симптом коллизии `1.`-нумерации (выживало только последнее поле).
    #    Это и есть «пустые карточки». Блокируем сборку.
    if len(all_pois) >= 5 and total_excerpts == 0 and not with_mentions:
        errors.append(
            f"{len(all_pois)} POI, но 0 выдержек И 0 счётчиков — поля POI не "
            "распарсились (вероятно коллизия `1.`-нумерации). Карточки выйдут "
            "пустыми (только название). Документ НЕ собран."
        )

    # 1 (WARN). Выдержки не распарсились при ненулевых counts.
    if with_mentions and not with_excerpts:
        warnings.append(
            f"0 выдержек распарсено при {len(with_mentions)} POI с ненулевыми "
            "counts — формат строки выдержки, вероятно, не совпал (ожидается "
            "`- {Автор} #{N} ({TIER}): {текст}`). Под POI не будет авторов."
        )
    elif with_mentions and len(with_excerpts) < 0.3 * len(with_mentions):
        warnings.append(
            f"выдержки есть лишь у {len(with_excerpts)} из {len(with_mentions)} "
            "POI с counts>0 — подозрительно мало, проверь формат строк выдержек."
        )

    # 2 (WARN). Lookup пуст: выдержки есть, но ни у одного автора нет URL/года.
    if with_excerpts and not any(
        ex.url or ex.year for p in all_pois for ex in p.excerpts
    ):
        warnings.append(
            "ни у одного автора нет URL/года — lookup из 1_dr_reports.md пуст. "
            "Причины: файл не приложен рядом, либо маркеры карточек / поля "
            "(URL/Автор/Дата) в нём в нестандартном формате."
        )

    # 3 (WARN). Trap-строка в сырье есть, но ни один POI не получил флаг trap.
    if re.search(r"\*\*[^\n*]*trap\s+archetype", (raw_body or "").lower()):
        if not any(p.trap_archetype for p in all_pois):
            warnings.append(
                "в md есть строка trap-archetype, но ни один POI не получил "
                "флаг trap — формат метки не совпал (ожидается "
                "`**⚠ Tourist-trap archetype:** …`)."
            )

    for m in errors:
        print(f"[stage3 ERROR] {m}", file=sys.stderr)
    for m in warnings:
        print(f"[stage3 warning] {m}", file=sys.stderr)
    return errors, warnings


# ---------------------------------------------------------------------------
# Coverage table data (общий хелпер для PDF и DOCX)
# ---------------------------------------------------------------------------

# Системное warning, всегда добавляется в Warnings секцию.
_COUNTS_VS_EXCERPTS_NOTE = (
    "ℹ️ Счётчики (HIGH: N) и выдержки в карточках могут не совпадать: "
    "счётчик — сколько разных авторов упомянули POI; выдержки — только "
    "те упоминания, где есть содержательная цитата. Автор, упомянувший "
    "POI без обоснования (например, в списке), попадает в счётчик, но "
    "не в выдержки. Это сделано намеренно: counts дают силу сигнала, "
    "выдержки — обоснование."
)


_TRAILING_MARKER_RE = re.compile(
    r"^\s*\*\*(?:Combined\s+with|Cluster|Iconic\s+status|"
    r"(?:⚠\s*)?(?:Tourist[-\s])?Trap\s+archetype|Iconic\s+exception):\*\*.*$",
    re.MULTILINE | re.IGNORECASE,
)


def _strip_trailing_markers(text: str) -> str:
    """Вырезать из текста характеристик трейлинг-маркеры
    `**Combined with:** ...`, `**Cluster:** ...` и т.п.
    Эти маркеры обрабатываются отдельно как chips."""
    cleaned = _TRAILING_MARKER_RE.sub("", text)
    return re.sub(r"\n{2,}", "\n", cleaned).strip()


# Fallback-маппинг русских регионов → English (для search query когда
# polish-маркер `[[регион: ... | english: ...]]` не задан). Pragmatic
# защита от плохих результатов поиска для общих английских терминов
# («Pub Street» — есть везде; нужен контекст). Расширять при появлении
# новых регионов в калибровочных кейсах.
_REGION_RU_TO_EN_FALLBACK = {
    "Сием-Рип и Ангкор":                          "Siem Reap, Cambodia",
    "Пномпень":                                    "Phnom Penh, Cambodia",
    "Баттамбанг":                                  "Battambang, Cambodia",
    "Луангпрабанг":                                "Luang Prabang, Laos",
    "Тямпасак и плато Боловен":                   "Champasak, Laos",
    "Нонгкхиав и долина Нам-Оу":                  "Nong Khiaw, Laos",
    "Центральный Меконг — Тхакхэк и карст Кхаммуан": "Thakhek, Laos",
}


# Маппинг популярных стран trip_id → English-имя для поисковых query.
# Покрывает текущие калибровочные кейсы (Камбоджа, Лаос, Вьетнам, Корея,
# Аргентина). При появлении новых направлений — расширять здесь.
_COUNTRY_MAP_RU_EN = {
    "камбоджа":    "Cambodia",
    "лаос":        "Laos",
    "вьетнам":     "Vietnam",
    "корея":       "Korea",
    "аргентина":   "Argentina",
    "таиланд":     "Thailand",
    "мьянма":      "Myanmar",
    "сингапур":    "Singapore",
    "малайзия":    "Malaysia",
    "индонезия":   "Indonesia",
    "филиппины":   "Philippines",
    "япония":      "Japan",
    "китай":       "China",
}


def _trip_countries_en(trip_id: str | None) -> list[str]:
    """Из `камбоджа_лаос_2026-02` → ['Cambodia', 'Laos']."""
    if not trip_id:
        return []
    out: list[str] = []
    for part in trip_id.split("_"):
        if re.fullmatch(r"\d{4}(?:-\d{2})?", part):
            break   # дошли до даты
        en = _COUNTRY_MAP_RU_EN.get(part.lower())
        if en and en not in out:
            out.append(en)
    return out


def _resolve_region_english(region_name: str, extracted: dict) -> str | None:
    """Резолв English-имени региона.

    Приоритет:
      1. polish-маркер `[[регион: NAME | english: ...]]` (записан в
         `region.english_name`)
      2. hardcoded `_REGION_RU_TO_EN_FALLBACK` для известных калибровочных
         регионов
      3. None — fallback на trip_countries в caller'е.
    """
    for region in extracted.get("regions", []):
        if region.name == region_name and region.english_name:
            return region.english_name
    return _REGION_RU_TO_EN_FALLBACK.get(region_name)


def _poi_search_query(
    name_local: str,
    region_english: str | None,
    fallback_countries: list[str],
    name_ru: str | None = None,
) -> str:
    """Сформировать query для Google Images поиска.

    Приоритет:
      1. `region_english` (из polish-маркера) — самый точный,
         например `Pub Street in Siem Reap, Cambodia`.
      2. fallback на страну(ы) из trip_id — `Pub Street in Cambodia or Laos`.
      3. голый name_local если ничего нет.

    Если латинского имени нет (`name_local` пуст) — запрос строится по
    **русскому** имени (`name_ru`), без хвостового описания в скобках
    («Центр Пекина (городская среда)» → «Центр Пекина»). Google картинки
    нормально ищут кириллицей; пустой запрос «… in {регион}» бесполезен.
    """
    base = (name_local or "").strip()
    if not base and name_ru:
        base = re.sub(r"\s*\([^)]*\)\s*$", "", name_ru).strip()
    if region_english:
        return f"{base} in {region_english.strip()}"
    if not fallback_countries:
        return base
    suffix = " or ".join(fallback_countries) if len(fallback_countries) > 1 \
        else fallback_countries[0]
    return f"{base} in {suffix}"


def _strip_field_label(text: str, labels: tuple[str, ...]) -> str:
    """Стрипает дублирующий label-префикс из поля POI.
    Возвращает стрипнутую строку (или исходную если ни один label не совпал)."""
    s = (text or "").strip()
    for prefix in labels:
        if s.lower().startswith(prefix.lower()):
            return s[len(prefix):].strip()
    return s


def _replace_author_ids(text: str, lookup: dict[str, dict]) -> str:
    """Заменить `cNN` (internal author id) на читаемое имя в строке.

    Используется для поля 5 (Характеристики) — авторы Stage 3 иногда
    ссылаются «По c04 ...», «по c33 ...». В презентационном выводе
    читателю это бессмысленно — подставляем имя автора (из lookup).
    Если автор не в lookup — оставляем cNN как есть (fail-soft).
    """
    if not text or not lookup:
        return text
    def repl(m: "re.Match[str]") -> str:
        cid = m.group(0)
        info = lookup.get(cid)
        if info and info.get("author_name"):
            return info["author_name"]
        return cid
    return re.sub(r"\bc\d{2,}\b", repl, text)


_CANONICAL_TAGS = ("обязательно", "можно", "не интересно")


def _normalize_tag(tag: str | None) -> str | None:
    """Вернуть тег региона, ЕСЛИ он уже одно из 3 канонических значений
    (обязательно / можно / не интересно); иначе None.

    Нормализация произвольных пользовательских формулировок («надо»,
    «нет», «если успеем») — НЕ программная, а через polish (T3b):
    LLM приводит тег к канону в md до рендера. Скрипт остаётся
    детерминированным и не угадывает синонимы. После первого round-trip
    (пользователь поставил [x] в DOCX → импорт пишет канон) значение
    всегда каноническое, так что точного сравнения достаточно.
    """
    if not tag:
        return None
    t = tag.strip().lower()
    return t if t in _CANONICAL_TAGS else None


def _capitalize_first(text: str) -> str:
    """`главное в регионе...` → `Главное в регионе...`. Безопасно к пустым."""
    if not text:
        return text
    return text[0].upper() + text[1:]


def _apply_region_markers(regions: list[Region], body: str) -> None:
    """Применить polish-маркеры `[[регион: <имя> | описание/авторы: ...]]`
    к собранным regions по совпадению name."""
    by_name = {r.name: r for r in regions}
    for m in _REGION_MARKER_RE.finditer(body):
        name = m.group(1).strip()
        kind = m.group(2).strip().lower()
        text = re.sub(r"\s+", " ", m.group(3).strip())
        region = by_name.get(name)
        if not region:
            continue
        if kind == "описание":
            region.polished_description = text
        elif kind == "авторы":
            region.polished_authors_summary = text
        elif kind == "english":
            region.english_name = text


def _add_author_bullet_docx(doc, a: dict) -> None:
    """Bullet-строка для автора в DOCX:
       `• Имя «Название отчёта» · 2024 · HIGH · 5 POI · domain.com`.

    Одна ссылка — как раньше (название plain, domain — hyperlink). Несколько
    отчётов у автора (поле 1 с 2+ URL) рендерятся по варианту 2:
      • есть метки `(Пекин)/(Сучжоу)` → каждая ссылка = метка-hyperlink;
      • меток нет → название = hyperlink на url1, остальные = «часть 2/3».
    """
    from docx.shared import Cm
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.6)
    D.set_para_spacing(p, 0, 1)
    D.add_run(p, "•  ", color=D.TEXT_DIM, size_pt=10)
    D.add_run(p, a["author_name"], bold=True, color=D.PRIMARY, size_pt=10)

    links = a.get("report_urls") or []
    multi = len(links) >= 2
    has_labels = multi and any(l.get("label") for l in links)
    title = a.get("report_title")

    # Название: при мульти-URL без меток — кликабельная ссылка на url1.
    if title:
        if multi and not has_labels:
            D.add_run(p, " ", size_pt=10)
            D.add_external_hyperlink(p, links[0]["url"], f"«{title}»",
                                     color=D.PRIMARY, size_pt=10)
        else:
            D.add_run(p, f" «{title}»", italic=True, color=D.TEXT, size_pt=10)

    parts: list[str] = []
    if a.get("year"):
        parts.append(str(a["year"]))
    if a.get("similarity"):
        parts.append(a["similarity"])
    parts.append(f"{a['poi_count']} POI")
    if parts:
        D.add_run(p, " · " + " · ".join(parts), color=D.TEXT_DIM, size_pt=10)

    def _link(url: str, text: str) -> None:
        D.add_run(p, " · ", color="9aa3ad", size_pt=10)
        D.add_external_hyperlink(p, url, text, color=D.PRIMARY, size_pt=10)

    if has_labels:
        for i, l in enumerate(links):
            _link(l["url"], l.get("label") or f"часть {i + 1}")
    elif multi:
        if not title:                                  # url1 без названия → домен
            _link(links[0]["url"], _url_domain(links[0]["url"]))
        for i, l in enumerate(links[1:], start=2):     # url2+ → «часть N»
            _link(l["url"], f"часть {i}")
    else:
        url = a.get("url")
        if url:
            _link(url, _url_domain(url))


def _format_author_line(a: dict) -> str:
    """Сформировать строку bullet-сводки автора per регион (PDF).

    `**Автор** «Название отчёта» · YEAR · TIER · N POI · domain.com`
    Markdown для рендера через `bullet_list` (md_inline_to_rl делает
    italic из `*...*`, link из `[text](url)`, bold из `**...**`).
    """
    line = f"**{a['author_name']}**"
    links = a.get("report_urls") or []
    multi = len(links) >= 2
    has_labels = multi and any(l.get("label") for l in links)
    title = a.get("report_title")

    # Название: при мульти-URL без меток — кликабельная ссылка на url1.
    if title:
        if multi and not has_labels:
            line += f" [«{title}»]({links[0]['url']})"
        else:
            line += f" *«{title}»*"

    parts = []
    if a.get("year"):
        parts.append(str(a["year"]))
    if a.get("similarity"):
        parts.append(a["similarity"])
    parts.append(f"{a['poi_count']} POI")
    if parts:
        line += " · " + " · ".join(parts)

    if has_labels:
        for i, l in enumerate(links):
            line += f" · [{l.get('label') or f'часть {i + 1}'}]({l['url']})"
    elif multi:
        if not title:                                  # url1 без названия → домен
            line += f" · [{_url_domain(links[0]['url'])}]({links[0]['url']})"
        for i, l in enumerate(links[1:], start=2):     # url2+ → «часть N»
            line += f" · [часть {i}]({l['url']})"
    elif a.get("url"):
        line += f" · [{_url_domain(a['url'])}]({a['url']})"
    return line


def _region_authors_summary(region: Region) -> list[dict]:
    """Агрегировать всех авторов, упомянувших POI этого региона.

    Возвращает список dict-ов, отсортированных по similarity tier (HIGH →
    OUTLIER → MEDIUM → LOW), затем по числу упомянутых POI убывания:
      {
        "author_id": "c02",
        "author_name": "Дария",
        "similarity": "HIGH",
        "url": "https://...",
        "year": 2024,
        "poi_count": 8,   # сколько разных POI упомянул в регионе
      }

    Используется для блока «Кто писал про регион» под region header.
    Даёт пользователю быстрый сигнал: глубина coverage, тон, ссылки на
    конкретные отчёты.
    """
    tier_order = {"HIGH": 0, "OUTLIER": 1, "MEDIUM": 2, "LOW": 3}
    by_author: dict[str, dict] = {}
    for poi in region.pois:
        for ex in poi.excerpts:
            key = ex.author_id
            if key not in by_author:
                by_author[key] = {
                    "author_id": ex.author_id,
                    "author_name": ex.author_name,
                    "similarity": ex.similarity,
                    "url": ex.url,
                    "year": ex.year,
                    "report_title": ex.report_title,
                    "report_urls": ex.report_urls,
                    "poi_count": 0,
                }
            by_author[key]["poi_count"] += 1
    out = list(by_author.values())
    out.sort(key=lambda a: (tier_order.get(a["similarity"], 99),
                            -a["poi_count"], a["author_name"]))
    return out


def _coverage_rows(extracted: dict) -> tuple[list[tuple[str, int, int, int, int, int, int, int]], tuple[int, ...]]:
    """Вернуть (rows, totals) для coverage-таблицы.

    Каждый row: (region_name, total, strong, weak, hidden, contested, red, low).
    Cluster sub-rows вставляются после своего региона с приставкой
    «Кластер — ...» (для приглушённого рендера и без link).
    """
    rows: list[tuple[str, int, int, int, int, int, int, int]] = []
    tots = [0, 0, 0, 0, 0, 0, 0]   # total, S, W, H, C, R, L
    for region in extracted["regions"]:
        s = sum(1 for p in region.pois if p.category == "STRONG CONFIRMED")
        w = sum(1 for p in region.pois if p.category == "WEAK CONFIRMED")
        h = sum(1 for p in region.pois if p.category == "HIDDEN GEM")
        c = sum(1 for p in region.pois if p.category == "CONTESTED")
        r = sum(1 for p in region.pois if p.category == "RED FLAG")
        low = sum(1 for p in region.pois if p.category == "LOW SIGNAL")
        rows.append((region.name, len(region.pois), s, w, h, c, r, low))
        tots[0] += len(region.pois); tots[1] += s; tots[2] += w
        tots[3] += h; tots[4] += c; tots[5] += r; tots[6] += low
        # Cluster sub-rows
        for cl in region.clusters:
            members = [p for p in region.pois if p.num in cl.member_nums]
            cs = sum(1 for p in members if p.category == "STRONG CONFIRMED")
            cw = sum(1 for p in members if p.category == "WEAK CONFIRMED")
            ch = sum(1 for p in members if p.category == "HIDDEN GEM")
            cc = sum(1 for p in members if p.category == "CONTESTED")
            cr = sum(1 for p in members if p.category == "RED FLAG")
            cl_low = sum(1 for p in members if p.category == "LOW SIGNAL")
            rows.append((
                f"Кластер — {cl.name}", cl.member_count,
                cs, cw, ch, cc, cr, cl_low,
            ))
    return rows, tuple(tots)


def _counts_line(poi: POI) -> str:
    """Строка `ВЫСОКАЯ: N (рек. X · нейтр. Y · крит. Z) · ОСОБЫЙ СИГНАЛ: ...`."""
    return (
        f"{_ac('HIGH')}: {poi.high_total} "
        f"(рек. {poi.high_recommend} · нейтр. {poi.high_neutral} · "
        f"крит. {poi.high_negative})   ·   "
        f"{_ac('OUTLIER')}: {poi.outlier_count}   ·   "
        f"{_ac('MEDIUM')}: {poi.medium_count}   ·   "
        f"{_ac('LOW')}: {poi.low_count}"
    )


def _poi_flags(
    poi: POI, *,
    for_docx: bool,
    name_to_num: dict[str, int] | None = None,
) -> list[dict]:
    """Собрать список chip'ов из POI.flags.

    for_docx=True → пытаемся добавить link_to_poi_num (int) для
    кликабельных переходов. name_to_num: глобальный map имён POI → их
    номера (один dict на весь документ); если целевой POI отсутствует в
    map (например, упоминается POI из другого региона, ещё не объявленный
    в md) — chip остаётся без link.
    """
    name_to_num = name_to_num or {}
    flags: list[dict] = []
    # Подписи чипов — из taxonomy `flag_badge` (firewall §7); kind — EN-ключи.
    if poi.iconic_status:
        kind = "iconic_world" if "world" in poi.iconic_status else "iconic_other"
        flags.append({"kind": kind,
                      "label": f"{taxonomy.label('flag_badge', 'iconic_status')}: "
                               f"{poi.iconic_status}"})
    if poi.trap_archetype:
        flags.append({"kind": "trap",
                      "label": f"{taxonomy.label('flag_badge', 'trap')}: "
                               f"{poi.trap_archetype['archetype']}"})
    if poi.iconic_exception:
        flags.append({"kind": "exception",
                      "label": taxonomy.label("flag_badge", "iconic_exception")})
    for cw in poi.combined_with:
        f = {"kind": "combined",
             "label": f"{taxonomy.label('flag_badge', 'combined_with')}: {cw['poi_name']}"}
        if for_docx:
            target_num = name_to_num.get(cw["poi_name"])
            if target_num is not None:
                f["link_to_poi"] = target_num
        flags.append(f)
    if poi.cluster_name:
        f = {"kind": "cluster",
             "label": f"{taxonomy.label('flag_badge', 'cluster')}: {poi.cluster_name}"}
        if for_docx:
            f["link_to_cluster"] = poi.cluster_name
        flags.append(f)
    return flags


def _build_name_to_num(extracted: dict) -> dict[str, int]:
    """Map name_ru → POI num для cross-reference линков."""
    out: dict[str, int] = {}
    for region in extracted["regions"]:
        for poi in region.pois:
            out[poi.name_ru] = poi.num
    return out


def check_author_urls(extracted: dict) -> dict:
    """Проверка: у всех ли уникальных авторов (cXX) есть URL отчёта.

    Возвращает dict:
      {
        "total_authors":      int,   # уникальных cXX по всему файлу
        "authors_with_url":   int,
        "authors_without_url": [{"author_id": ..., "author_name": ...,
                                  "appears_in_pois": [...]}],
      }

    Используется как:
      - sanity-warning в stderr при build (поймать unmatched cXX)
      - возвращаемое значение для CLI/тестов
      - в polish-prompt T6a встречается требование «у всех авторов
        должна быть ссылка» — этот checker валидирует пайплайн.

    Pure фильтр, не мутирует extracted.
    """
    seen: dict[str, dict] = {}
    for region in extracted["regions"]:
        for poi in region.pois:
            for ex in poi.excerpts:
                e = seen.setdefault(ex.author_id, {
                    "author_id": ex.author_id,
                    "author_name": ex.author_name,
                    "url": ex.url,
                    "appears_in_pois": [],
                })
                e["appears_in_pois"].append(f"#{poi.num} {poi.name_ru}")
                # Если хотя бы у одной выдержки этого автора есть URL —
                # считаем что автор «с url». Пересохраняем url если был None.
                if ex.url and not e["url"]:
                    e["url"] = ex.url

    without_url = [
        {
            "author_id": e["author_id"],
            "author_name": e["author_name"],
            "appears_in_pois": e["appears_in_pois"][:5],  # первые 5
            "appears_count": len(e["appears_in_pois"]),
        }
        for e in seen.values() if not e["url"]
    ]
    return {
        "total_authors":      len(seen),
        "authors_with_url":   sum(1 for e in seen.values() if e["url"]),
        "authors_without_url": without_url,
    }


def _emit_url_warnings(extracted: dict) -> None:
    """Печать warning в stderr если у каких-то авторов нет URL.

    Не блокирует рендер (PDF/DOCX всё равно соберётся, просто без линков
    у этих авторов). Цель — заметность edge case при экспорте.
    """
    import sys as _sys
    check = check_author_urls(extracted)
    if not check["authors_without_url"]:
        return
    print(
        f"\n[stage3] предупреждение: у {len(check['authors_without_url'])}"
        f" из {check['total_authors']} авторов нет URL отчёта."
        f" Возможные причины:\n"
        f"  - 1_dr_reports.md не приложен или лежит не рядом;\n"
        f"  - автор в Stage 3 имеет cXX-id, которого нет в Stage 1;\n"
        f"  - формат поля 1 в Stage 1 не распознан парсером.\n"
        f"Авторы без URL:",
        file=_sys.stderr,
    )
    for a in check["authors_without_url"][:10]:
        print(
            f"  • {a['author_id']} {a['author_name']!r}"
            f" (упомянут в {a['appears_count']} POI)",
            file=_sys.stderr,
        )


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

def _gate_validation(extracted: dict) -> None:
    """Гейт целостности: критичные расхождения парсинга → не собирать документ."""
    errs = extracted.get("validation_errors") or []
    if errs:
        raise RuntimeError(
            "Stage 3 export — парсинг неполон (документ НЕ собран):\n  - "
            + "\n  - ".join(errs)
            + "\nИсправь 3_poi_pool.md / polished.md и повтори.")
    for w in extracted.get("warnings") or []:
        print(f"[stage3 warning] {w}", file=sys.stderr)


def build_pdf(extracted: dict, output_path: str | Path) -> str:
    """Сгенерировать PDF Stage 3 (read-only витрина POI агрегации)."""
    _gate_validation(extracted)
    P.register_fonts()
    styles = P.get_styles()
    P.clear_section_anchors()

    name_to_num = _build_name_to_num(extracted)
    trip_countries = _trip_countries_en(extracted.get("trip_id"))

    # Регистрируем якоря для cross-links (## Heading → slug).
    anchors = {region.name: f"region_{_slug(region.name)}"
               for region in extracted["regions"]}
    P.set_section_anchors(anchors)

    doc = P.make_doc(str(output_path), orientation="portrait")
    story: list = []

    # === Cover ===
    cover_title = _cover_title(extracted)
    story.append(P.para(cover_title, styles["cover_title"]))
    story.append(P.para(_cover_subtitle(extracted), styles["cover_subtitle"]))
    story.append(P.spacer(8))

    # Параметры
    story.append(P.key_params_table(_cover_params(extracted)))
    story.append(P.spacer(12))

    # Таблица «Распределение по категориям» убрана (Р11) — «Покрытие по
    # регионам» ниже несёт те же числа (строка ВСЕГО), дублировать не нужно.

    # Warnings (как warning-box) + всегда добавляем системное предупреждение
    # про counts vs excerpts (асимметрия чисел в карточках — feature, не bug).
    warnings_all = [html_lib.ru_anglicisms(w) for w in extracted["warnings"]] \
        + [_COUNTS_VS_EXCERPTS_NOTE]
    story.append(P.heading_paragraph(
        "Предупреждения", styles["h2"],
        outline_level=0, anchor_slug="warnings",
    ))
    story.append(P.warning_box_bullets(warnings_all, styles))
    story.append(P.spacer(12))

    # Coverage table — пока через generic data_table (без линков; PDF
    # навигация через outline)
    rows, tots = _coverage_rows(extracted)
    if rows:
        story.append(P.heading_paragraph(
            "Покрытие по регионам", styles["h2"],
            outline_level=0, anchor_slug="coverage",
        ))
        cov_data = [["Регион", "POI"] +
                    [taxonomy.label("poi_category_badge", k) for k in _POI_CAT_ORDER]]
        for region, t, s, w, h, c, r, low in rows:
            cov_data.append([
                region, str(t),
                str(s) if s else "·", str(w) if w else "·",
                str(h) if h else "·", str(c) if c else "·",
                str(r) if r else "·", str(low) if low else "·",
            ])
        cov_data.append(["ВСЕГО", str(tots[0]), str(tots[1]), str(tots[2]),
                         str(tots[3]), str(tots[4]), str(tots[5]),
                         str(tots[6])])
        # Явные ширины: при авто-раскладке имена регионов зажимались в 3
        # строки. Даём «Региону» ~26%, числовые колонки узкие (контент «·»/N).
        story.append(P.data_table(
            cov_data, header=True,
            col_widths=["26%", "10%", "11%", "11%", "11%", "11%", "10%", "10%"],
        ))
        story.append(P.spacer(16))

    # === Регионы и POI ===
    for region in extracted["regions"]:
        slug = anchors[region.name]
        story.append(P.section_bar(
            f"{region.name}  ·  {region.poi_count} POI",
            anchor_slug=slug, outline_level=0,
        ))
        # 1. Описание (polished или fallback из Stage 0)
        if region.polished_description:
            story.append(P.para(
                _capitalize_first(region.polished_description),
                styles["body"],
            ))
        # 2. Тег региона — read-only badge, ТОЛЬКО если заполнен (после
        #    round-trip из DOCX). Симметрично user_comment: пустой тег в
        #    PDF скрываем (его задача — заполняться в DOCX, не в PDF).
        tag_norm = _normalize_tag(region.tag)
        if tag_norm:
            tag_color = {
                "обязательно":  S.COLORS["primary"],
                "можно":        S.COLORS["warning"],
                "не интересно": S.COLORS["danger"],
            }.get(tag_norm, S.COLORS["primary"])
            story.append(P.labeled_para(
                "Тег региона:", tag_norm, styles["body"],
                color=tag_color,
            ))
        # 2b. Комментарий к региону — только если заполнен (как тег).
        if region.user_comment:
            story.append(P.labeled_para(
                "Комментарий к региону:", region.user_comment, styles["body"],
            ))
        # 3. Сводка по авторам
        if region.polished_authors_summary:
            story.append(P.spacer(2))
            story.append(P.para(
                f"**Кто писал про регион:** {region.polished_authors_summary}",
                styles["body"],
            ))
        else:
            authors = _region_authors_summary(region)
            if authors:
                story.append(P.spacer(2))
                story.append(P.para("**Кто писал про регион:**",
                                    styles["body"]))
                story.extend(P.bullet_list(
                    [_format_author_line(a) for a in authors],
                    styles,
                ))
        story.append(P.spacer(6))

        # Cluster header + члены идут в порядке появления в md.
        # Простейший подход: рендерим cluster header перед первым из его
        # member-POI, затем member-POI, затем остальные POI без кластера.
        rendered_clusters: set[str] = set()
        for poi in region.pois:
            if poi.cluster_name and poi.cluster_name not in rendered_clusters:
                # Найдём cluster object
                cl = next((c for c in region.clusters
                           if c.name == poi.cluster_name), None)
                if cl:
                    story.append(P.poi_cluster_header(
                        name=cl.name,
                        member_count=cl.member_count,
                        note=cl.note,
                    ))
                    story.append(P.spacer(4))
                rendered_clusters.add(poi.cluster_name)
            story.append(P.poi_card(
                num=poi.num,
                name_ru=poi.name_ru,
                name_local=poi.name_local,
                category=poi.category,
                counts_line=_counts_line(poi),
                excerpts=[
                    {
                        "tone": ex.tone,
                        "author_name": ex.author_name,
                        "year": ex.year,
                        "similarity": ex.similarity,
                        "url": ex.url,
                        "report_title": ex.report_title,
                        "text": ex.text,
                    }
                    for ex in poi.excerpts
                ],
                characteristics=poi.characteristics,
                flags=_poi_flags(poi, for_docx=False,
                                 name_to_num=name_to_num),
                user_comment=poi.user_comment,
                title_link=D.google_images_url(_poi_search_query(
                    poi.name_local,
                    _resolve_region_english(poi.region, extracted),
                    trip_countries,
                    name_ru=poi.name_ru,
                )),
            ))
            story.append(P.spacer(8))

    # === Находки вне турпотока (non-mainstream, если есть) ===
    if extracted["non_mainstream"]:
        story.append(P.heading_paragraph(
            "Находки вне турпотока", styles["h2"],
            outline_level=0, anchor_slug="non_mainstream",
        ))
        story.append(P.para(extracted["non_mainstream"], styles["body"]))

    # ─── Легенда таксонов (Р2): соответствие RU↔EN одной сноской ──────────
    story.append(P.spacer(10))
    story.append(P.para(
        "Категории POI и авторов (RU = EN из исходных артефактов): "
        + taxonomy.legend("poi_category", "author_category"),
        styles["small"], highlight_todo=False))

    P.set_footer_text(_footer_text(extracted))
    P.build_doc(doc, story)
    P.clear_section_anchors()
    return str(output_path)


# ---------------------------------------------------------------------------
# DOCX builder
# ---------------------------------------------------------------------------

def build_docx(extracted: dict, output_path: str | Path) -> str:
    """Сгенерировать DOCX Stage 3 (operative-документ для заполнения)."""
    _gate_validation(extracted)
    from docx import Document
    from docx.shared import Cm

    D.reset_bookmark_id()
    name_to_num = _build_name_to_num(extracted)
    trip_countries = _trip_countries_en(extracted.get("trip_id"))

    doc = Document()
    # Гарантируем native Hyperlink style в styles.xml — без него Pages
    # и Google Docs не показывают `<w:hyperlink>` как кликабельный.
    D._ensure_hyperlink_style(doc)
    for sec in doc.sections:
        sec.top_margin = Cm(2)
        sec.bottom_margin = Cm(2)
        sec.left_margin = Cm(2)
        sec.right_margin = Cm(2)

    # === Cover ===
    t = doc.add_paragraph()
    D.set_para_spacing(t, 0, 4)
    D.add_run(t, _cover_title(extracted), bold=True,
              color=D.PRIMARY, size_pt=22)
    sub = doc.add_paragraph()
    D.set_para_spacing(sub, 0, 16)
    D.add_run(sub, _cover_subtitle(extracted), italic=True,
              color="3b4554", size_pt=11)

    D.add_key_params_table(doc, rows=_cover_params(extracted))
    doc.add_paragraph()

    # Таблица «Распределение по категориям» убрана (Р11) — «Покрытие по
    # регионам» ниже несёт те же числа (строка ВСЕГО), дублировать не нужно.

    # Warnings — всегда добавляем системную ноту про counts vs excerpts
    warnings_all = [html_lib.ru_anglicisms(w) for w in extracted["warnings"]] \
        + [_COUNTS_VS_EXCERPTS_NOTE]
    h = doc.add_paragraph()
    D.set_para_spacing(h, 8, 4)
    D.add_run(h, "Предупреждения", bold=True, color=D.PRIMARY, size_pt=13)
    for w in warnings_all:
        wp = doc.add_paragraph()
        wp.paragraph_format.left_indent = Cm(0.4)
        D.set_para_spacing(wp, 0, 2)
        D.add_run(wp, "• " + w, color=D.TEXT, size_pt=10)
    doc.add_paragraph()

    # Coverage
    rows, tots = _coverage_rows(extracted)
    if rows:
        h = doc.add_paragraph()
        D.set_para_spacing(h, 12, 4)
        D.add_run(h, "Покрытие по регионам", bold=True,
                  color=D.PRIMARY, size_pt=13)
        D.add_coverage_table(doc, rows=rows, totals=tots)
        doc.add_paragraph()

    # === Регионы и POI ===
    for region in extracted["regions"]:
        # 1. Заголовок-плашка
        D.add_region_header(
            doc,
            name=region.name,
            poi_count=region.poi_count,
        )
        # 2. Описание (polished LLM или fallback из Stage 0 «Принципиально:»)
        if region.polished_description:
            d = doc.add_paragraph()
            D.set_para_spacing(d, 6, 4)
            D.add_run(d, _capitalize_first(region.polished_description),
                      color=D.TEXT, size_pt=11)
        # 3. Тег региона (anketa-style чекбоксы). Если тег уже заполнен
        #    (из предыдущего round-trip), pre-select'им соответствующий
        #    чекбокс — нормализуя пользовательские синонимы («надо» →
        #    «обязательно», «нет» → «не интересно»).
        tag_selected = _normalize_tag(region.tag)
        D.add_choice_question(
            doc,
            label="Тег региона",
            options=["обязательно", "можно", "не интересно"],
            selected=[tag_selected] if tag_selected else [],
            multi=False,
            hint="поставь «x» в скобках выбранного",
        )
        # 4. Сводка по авторам: polished (LLM) или deterministic fallback
        if region.polished_authors_summary:
            sa = doc.add_paragraph()
            D.set_para_spacing(sa, 8, 2)
            D.add_run(sa, "Кто писал про регион: ",
                      bold=True, color="3b4554", size_pt=11)
            D.add_run(sa, region.polished_authors_summary,
                      color=D.TEXT, size_pt=11)
        else:
            authors = _region_authors_summary(region)
            if authors:
                lbl = doc.add_paragraph()
                D.set_para_spacing(lbl, 8, 2)
                D.add_run(lbl, "Кто писал про регион:",
                          bold=True, color="3b4554", size_pt=11)
                for a in authors:
                    _add_author_bullet_docx(doc, a)

        rendered_clusters: set[str] = set()
        for poi in region.pois:
            if poi.cluster_name and poi.cluster_name not in rendered_clusters:
                cl = next((c for c in region.clusters
                           if c.name == poi.cluster_name), None)
                if cl:
                    D.add_cluster_header(
                        doc, name=cl.name,
                        member_count=cl.member_count, note=cl.note,
                    )
                rendered_clusters.add(poi.cluster_name)
            D.add_poi_card(
                doc,
                num=poi.num,
                name_ru=poi.name_ru,
                name_local=poi.name_local,
                category=poi.category,
                counts_line=_counts_line(poi),
                excerpts=[
                    {
                        "tone": ex.tone,
                        "author_name": ex.author_name,
                        "year": ex.year,
                        "similarity": ex.similarity,
                        "url": ex.url,
                        "report_title": ex.report_title,
                        "text": ex.text,
                    }
                    for ex in poi.excerpts
                ],
                characteristics=poi.characteristics,
                flags=_poi_flags(poi, for_docx=True,
                                 name_to_num=name_to_num),
                user_comment=poi.user_comment,
                search_query=_poi_search_query(
                    poi.name_local,
                    _resolve_region_english(poi.region, extracted),
                    trip_countries,
                    name_ru=poi.name_ru,
                ),
            )
            doc.add_paragraph()

    # Находки вне турпотока (non-mainstream)
    if extracted["non_mainstream"]:
        h = doc.add_paragraph()
        D.set_para_spacing(h, 12, 4)
        D.add_run(h, "Находки вне турпотока", bold=True,
                  color=D.PRIMARY, size_pt=13)
        for line in extracted["non_mainstream"].splitlines():
            ls = line.strip()
            if not ls:
                continue
            np = doc.add_paragraph()
            D.set_para_spacing(np, 0, 2)
            D.add_run(np, ls, color=D.TEXT, size_pt=10)

    # ─── Легенда таксонов (Р2): соответствие RU↔EN одной сноской ──────────
    leg = doc.add_paragraph()
    D.set_para_spacing(leg, 12, 2)
    D.add_run(leg, "Категории POI и авторов (RU = EN из исходных артефактов): "
              + taxonomy.legend("poi_category", "author_category"),
              color=D.TEXT_DIM, size_pt=8)

    doc.save(str(output_path))
    return str(output_path)


# ---------------------------------------------------------------------------
# Cover helpers
# ---------------------------------------------------------------------------

def _cover_title(extracted: dict) -> str:
    # «камбоджа_лаос_2026-02» → «Камбоджа + Лаос · агрегация POI»;
    # «вьетнам_север_…» → «Северный Вьетнам · агрегация POI».
    geo = CC.humanize_trip_geo(extracted.get("trip_id"), join=" + ", default="")
    # Fallback без тех-слага «Stage 3» в видимом заголовке.
    return f"{geo} · агрегация POI" if geo else "Агрегация POI"


def _cover_subtitle(extracted: dict) -> str:
    total = extracted.get("total_pois") or sum(
        len(r.pois) for r in extracted["regions"]
    )
    n_regions = len(extracted["regions"])
    # Без pipeline-жаргона «Stage 3 · trip_id» — только содержательная сводка.
    return f"{n_regions} регион(а/ов) · {total} POI"


def _profile_display_name(profile_path: str | None) -> str:
    """`profiles/алексей.md` → `Алексей`. Без расширения, capitalize."""
    if not profile_path:
        return "—"
    name = Path(str(profile_path)).stem
    return name[:1].upper() + name[1:] if name else "—"


def _cover_params(extracted: dict) -> list[tuple[str, str]]:
    """Параметры на cover — единый паспорт поездки (Кто едет + Регионы).

    `Trip ID` / `Создано` убраны (pipeline-поля; дата — в футере). Всего POI
    и число регионов — в подзаголовке, не дублируем. `Режим агрегации`
    (scarce/abundant) — внутренняя методология, не выводится.
    """
    geo = CC.humanize_trip_geo(
        extracted.get("trip_id"), join=" + ", default="") or None
    return CC.passport_rows(
        who=extracted.get("who_goes") or CC.profile_name(extracted.get("travelers_profile")),
        geo=geo,
    )


def _footer_text(extracted: dict) -> str:
    # Единый футер со всеми стадиями: левый — «создан {date}» (или пусто),
    # правый «стр. N» рисует pdf_lib. Без breadcrumb-фоллбэка «агрегация POI».
    created = extracted.get("created") or ""
    return f"создан {created}".strip() if created else ""


def _slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return s


# ---------------------------------------------------------------------------
# Renderer entry — регистрируется для обоих форматов
# ---------------------------------------------------------------------------

def _guess_neighbour(
    output_path: str | Path,
    source_file: str | Path | None,
    candidates_relative: list[str],
) -> Path | None:
    """Найти соседний файл рядом с source_file или output_path."""
    bases: list[Path] = []
    if source_file:
        bases.append(Path(source_file).parent)
    bases.append(Path(output_path).parent)
    for base in bases:
        for rel in candidates_relative:
            candidate = base / rel
            if candidate.exists():
                return candidate
    return None


def _guess_stage1_path(
    output_path: str | Path,
    source_file: str | Path | None = None,
) -> Path | None:
    """Fallback-поиск соседнего `1_dr_reports.md` — ТОЛЬКО для старых Stage 3
    файлов без встроенного реестра авторов (`## Источники (реестр авторов)`).
    Self-contained путь («1 файл») не вызывает поиск: lookup берётся из реестра
    в самом Stage 3 md (см. `load_author_registry`)."""
    return _guess_neighbour(output_path, source_file, ["1_dr_reports.md"])


def _guess_stage0_path(
    output_path: str | Path,
    source_file: str | Path | None = None,
) -> Path | None:
    """Stage 0 файл — может называться `0_scope.md` (production) или
    `0_scope_opus.md` / `0_scope_sonnet.md` (калибровочные двойники)."""
    return _guess_neighbour(
        output_path, source_file,
        ["0_scope.md", "0_scope_opus.md", "0_scope_sonnet.md"],
    )


# ---------------------------------------------------------------------------
# IMPORT (round-trip DOCX → md): извлечь заполненные теги + комментарии
# ---------------------------------------------------------------------------

def _xml_text(elem) -> str:
    """Собрать весь текст (`w:t`) внутри XML-элемента."""
    from docx.oxml.ns import qn
    return "".join(t.text or "" for t in elem.findall(".//" + qn("w:t")))


def _bookmark_names(elem) -> list[str]:
    """Имена всех bookmarkStart внутри элемента."""
    from docx.oxml.ns import qn
    return [b.get(qn("w:name"))
            for b in elem.findall(".//" + qn("w:bookmarkStart"))
            if b.get(qn("w:name"))]


_CHECKBOX_RE = re.compile(
    r"\[\s*[xXхХ✓]\s*\]\s*(обязательно|можно|не\s+интересно)",
    re.IGNORECASE,
)
_COMMENT_FIELD_RE = re.compile(r"Комментарий:\s*(.*)", re.DOTALL)


def parse_docx_for_import(docx_path: str | Path) -> dict:
    """Извлечь из заполненного Stage 3 DOCX проставленные теги и комментарии.

    Опирается на bookmarks, расставленные при экспорте:
      - `region_<slug>` в плашке региона → следом идут body-параграфы
        `[ ]/[x] обязательно|можно|не интересно`;
      - `poi_<num>` в карточке POI → параграф «Комментарий: <текст>».

    Возвращает:
      {
        "region_tags":   {region_slug: "обязательно"|"можно"|"не интересно"},
        "poi_comments":  {poi_num: "текст комментария"},
        "warnings":      [str, ...],
      }

    Slug региона резолвится в имя caller'ом (import_docx) через сравнение
    с region_anchor(name) регионов из оригинального md.
    """
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(str(docx_path))
    body = doc.element.body

    region_tags: dict[str, str] = {}
    poi_comments: dict[int, str] = {}
    warnings: list[str] = []

    current_region_slug: str | None = None

    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:tbl"):
            names = _bookmark_names(child)
            region_bm = next(
                (n for n in names if n.startswith("region_")), None)
            poi_bm = next(
                (n for n in names if re.fullmatch(r"poi_\d+", n)), None)
            if region_bm:
                current_region_slug = region_bm
            if poi_bm:
                num = int(poi_bm.split("_")[1])
                comment = _extract_comment_from_table(child)
                if comment:
                    poi_comments[num] = comment
        elif tag == qn("w:p"):
            # Чекбокс тега — body-level параграф после плашки региона.
            text = _xml_text(child).strip()
            m = _CHECKBOX_RE.search(text)
            if m and current_region_slug:
                value = re.sub(r"\s+", " ", m.group(1).strip().lower())
                if current_region_slug in region_tags:
                    # Пользователь отметил >1 чекбокса в одном регионе
                    warnings.append(
                        f"регион {current_region_slug}: отмечено несколько "
                        f"тегов — взят первый ({region_tags[current_region_slug]})"
                    )
                else:
                    region_tags[current_region_slug] = value

    return {
        "region_tags":  region_tags,
        "poi_comments": poi_comments,
        "warnings":     warnings,
    }


def _extract_comment_from_table(tbl_elem) -> str:
    """Из POI-таблицы извлечь текст после «Комментарий:».

    Параграф «Комментарий: <текст>» — последний в карточке. Берём текст
    после двоеточия; пустой («Комментарий: ») → "".
    """
    from docx.oxml.ns import qn
    for p in tbl_elem.findall(".//" + qn("w:p")):
        text = _xml_text(p)
        m = _COMMENT_FIELD_RE.search(text)
        if m:
            return m.group(1).strip()
    return ""


_MD_COMMENT_LINE_RE = re.compile(
    r"^(\s*6\.\s+Комментарий\s+пользователя:\s*)(.*)$",
)
_MD_TAG_IN_HEADER_RE = re.compile(r"(\*\*тег:\*\*\s*)(.+?)\s*$")


def import_docx(docx_path: str | Path, md_path: str | Path) -> dict:
    """Round-trip: применить заполненный DOCX к исходному
    `3_poi_aggregation.md` inplace.

    - Теги регионов (`[x]` в DOCX) → в заголовок `### … · **тег:** <значение>`.
    - Комментарии POI → в поле `6. Комментарий пользователя: <текст>`.
    - Counts / выдержки / категории НЕ трогаем (вычисляемые данные).

    Edge cases:
      - пустой тег / комментарий в DOCX → НЕ перезаписываем исходное;
      - регион/POI из DOCX, которого нет в md → warning, пропуск;
      - conflict: md изменён ПОЗЖЕ экспорта DOCX → warning (по mtime).

    Ограничение v1: комментарий записывается одной строкой (многострочный
    из DOCX склеивается). Если в исходном md поле 6 было многострочным —
    continuation-строки не очищаются (типичный комментарий однострочный).

    Возвращает {tags_applied, comments_applied, warnings}.
    """
    import os

    docx_path = Path(docx_path)
    md_path = Path(md_path)
    parsed = parse_docx_for_import(docx_path)
    md_text = md_path.read_text(encoding="utf-8")

    warnings: list[str] = list(parsed["warnings"])

    # Conflict: md новее DOCX → возможно правки разошлись.
    try:
        if md_path.stat().st_mtime > docx_path.stat().st_mtime + 1:
            warnings.append(
                f"⚠️ {md_path.name} изменён позже экспорта DOCX — твои "
                f"правки в DOCX могут конфликтовать с более новой версией md"
            )
    except OSError:
        pass

    # Резолв slug → имя региона (через тот же region_anchor что и экспорт).
    slug_to_name: dict[str, str] = {}
    for m in _REGION_HEADER_RE.finditer(md_text):
        name = m.group(1).strip()
        slug_to_name[D.region_anchor(name)] = name
    tag_by_name: dict[str, str] = {}
    for slug, tag in parsed["region_tags"].items():
        name = slug_to_name.get(slug)
        if name:
            tag_by_name[name] = tag
        else:
            warnings.append(
                f"регион (slug={slug}) из DOCX не найден в md — тег пропущен")

    poi_comments = parsed["poi_comments"]
    md_poi_nums = {int(m.group(1)) for m in _POI_HEADER_RE.finditer(md_text)}
    for num in poi_comments:
        if num not in md_poi_nums:
            warnings.append(
                f"POI #{num} из DOCX не найден в md — комментарий пропущен")

    # Построчная правка.
    lines = md_text.split("\n")
    out: list[str] = []
    current_poi: int | None = None
    tags_applied = 0
    comments_applied = 0

    for line in lines:
        rm = _REGION_HEADER_RE.match(line)
        if rm:
            name = rm.group(1).strip()
            new_tag = tag_by_name.get(name)
            if new_tag:
                if "**тег:**" in line:
                    line = _MD_TAG_IN_HEADER_RE.sub(
                        lambda mm: mm.group(1) + new_tag, line)
                else:
                    line = line.rstrip() + f" · **тег:** {new_tag}"
                tags_applied += 1
            out.append(line)
            current_poi = None
            continue

        pm = _POI_HEADER_RE.match(line)
        if pm:
            current_poi = int(pm.group(1))
            out.append(line)
            continue

        cm = _MD_COMMENT_LINE_RE.match(line)
        if cm and current_poi is not None:
            new_comment = poi_comments.get(current_poi)
            if new_comment:
                # Нормализуем label с одним пробелом после двоеточия.
                indent = cm.group(1)[:len(cm.group(1)) - len(cm.group(1).lstrip())]
                line = f"{indent}6. Комментарий пользователя: {new_comment}"
                comments_applied += 1
            out.append(line)
            continue

        out.append(line)

    new_md = "\n".join(out)
    if new_md != md_text:
        md_path.write_text(new_md, encoding="utf-8")

    return {
        "tags_applied":     tags_applied,
        "comments_applied": comments_applied,
        "warnings":         warnings,
    }


# ---------------------------------------------------------------------------
# Render wrappers
# ---------------------------------------------------------------------------

def render_stage3_pdf(
    parsed: dict, *, recipient: str = "self",
    output_path: str | Path,
    source_file: str | Path | None = None,
    **_unused,
) -> "renderer_module_RenderRequest":   # noqa
    """PDF wrapper для registered renderer."""
    stage1_path = _guess_stage1_path(output_path, source_file)
    stage0_path = _guess_stage0_path(output_path, source_file)
    extracted = extract_content(
        parsed, stage1_path=stage1_path, stage0_path=stage0_path,
        input_path=[source_file, output_path],
    )
    _emit_url_warnings(extracted)
    pdf_path = build_pdf(extracted, output_path)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "trip_id": extracted.get("trip_id"),
            "regions": len(extracted["regions"]),
            "total_pois": sum(len(r.pois) for r in extracted["regions"]),
        },
        metadata={
            "trip_id":   extracted.get("trip_id"),
            "stage":     "3_poi_aggregation",
            "recipient": recipient,
        },
        notes=[f"PDF (read-only витрина): {pdf_path}"],
    )


def render_stage3_docx(
    parsed: dict, *, recipient: str = "self",
    output_path: str | Path,
    source_file: str | Path | None = None,
    **_unused,
) -> "renderer_module_RenderRequest":   # noqa
    """DOCX wrapper для registered renderer."""
    stage1_path = _guess_stage1_path(output_path, source_file)
    stage0_path = _guess_stage0_path(output_path, source_file)
    extracted = extract_content(
        parsed, stage1_path=stage1_path, stage0_path=stage0_path,
        input_path=[source_file, output_path],
    )
    _emit_url_warnings(extracted)
    docx_path = build_docx(extracted, output_path)
    return _renderer.RenderRequest(
        format="docx",
        output_path=docx_path,
        content={
            "trip_id": extracted.get("trip_id"),
            "regions": len(extracted["regions"]),
            "total_pois": sum(len(r.pois) for r in extracted["regions"]),
        },
        metadata={
            "trip_id":   extracted.get("trip_id"),
            "stage":     "3_poi_aggregation",
            "recipient": recipient,
        },
        notes=[
            f"DOCX (operative-документ для заполнения тегов / комментариев): "
            f"{docx_path}",
        ],
    )


_renderer.register_renderer("3_poi_aggregation", "pdf", render_stage3_pdf)
_renderer.register_renderer("3_poi_aggregation", "docx", render_stage3_docx)
_renderer.register_renderer("3_stage", "pdf", render_stage3_pdf)
_renderer.register_renderer("3_stage", "docx", render_stage3_docx)

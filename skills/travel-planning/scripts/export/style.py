"""style.py — фиксированный визуальный стиль для всех экспортов.

**Контракт формата** артефактов-источников (таксоны/секции, эволюционирующий
контент) — каноны `references/stageN/stageN-output-spec.md`; сверка —
`tests/test_format_contract.py`.

Принцип (export-design.md §5):
  - Visual style + structure = ФИКСИРОВАНЫ для всех стадий и всех поездок.
    Никакой кастомизации per-trip.
  - Content extracted from stage files = ГИБОК (эволюционирует со спекой
    стадий, см. §6 schema evolution).

Этот файл — единственная точка, где задаются цвета, шрифты, размеры,
иконки. Stage-модули и template-файлы ссылаются на эти константы, не
определяют свои.
"""
from __future__ import annotations

# taxonomy — словарь таксонов (scripts/taxonomy.py). Используется только для
# отображаемых ярлыков (CATEGORY_SHORT); ключи-доступы к цветам — EN.
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    import taxonomy


# ---------------------------------------------------------------------------
# Цветовая палитра (export-design.md §5)
# ---------------------------------------------------------------------------

# Дизайн-токены «Современный путеводитель» (IBM Plex Sans/Mono, teal-акцент).
# Перенесено из tokens.css проекта Claude Design (oklch→sRGB hex, тинты —
# скомпонованы над бумагой #f3f4f2). Семантика тонов:
#   • accent  #26706e — десатурированный teal: заголовки, плашки, ссылки, акцент;
#   • warn    #b57631 — охра: предупреждение / переезд / TODO;
#   • danger  #b9473d — приглушённый красный: критично / red flag;
#   • info    #4a6f93 — slate-синий: справка (НЕ риск);
#   • paper   #f3f4f2 — тёплый серо-белый фон листа; ink #1b1e1c — текст.
# Ключи-имена сохранены обратносовместимыми (компоненты читают `primary`,
# `section_bar_bg`, `warn_bg` …) — значения перенаправлены на новую палитру.
COLORS = {
    # ── База палитры (tokens.css :root) ──
    "paper":        "#f3f4f2",  # фон листа
    "ink":          "#1b1e1c",  # основной текст
    "muted":        "#5d645f",  # вторичный текст
    "line":         "#dee2db",  # hairline-линии, рамки
    "accent":       "#26706e",  # teal — основной акцент
    "accent_dark":  "#004b49",  # тёмный teal — текст чипа/sig-strong
    "warn":         "#b57631",  # охра — warning / переезд / TODO
    "info":         "#4a6f93",  # slate — справка

    # ── Обратносовместимые семантические ключи (перенаправлены) ──
    "primary":      "#26706e",  # accent teal — заголовки, плашки, ссылки
    "secondary":    "#b57631",  # warm accent
    "warning":      "#b57631",  # охра — warning / caution / TODO-линия
    "danger":       "#b9473d",  # приглушённый красный
    "text":         "#1b1e1c",  # ink
    "background":   "#ffffff",  # белый — карточки, отель, текст-на-акценте
    "background_alt": "#eaeeec",  # accent .045 — лёгкое выделение
    "accent_stripe": "#26706e",  # тонкая accent-полоса вверху страницы

    # Плашки (визуальные якоря — день / секция).
    "day_bar_bg":      "#26706e",  # accent-плашка дня (interim — editorial day след. проходом)
    "section_bar_bg":  "#26706e",  # залитая accent-плашка H2-секции
    "bar_text":        "#ffffff",  # белый текст на плашках
    "bar_text_dim":    "#cfe0df",  # приглушённый белый (конвертация ₽ в бюджете)

    # Warning-box (левый edge + тинтованный фон).
    "warn_bg":      "#ece5db",  # warn .12 над бумагой
    "warn_border":  "#b57631",  # охра-edge
    "warn_text":    "#7b410f",  # тёмная охра — текст/лейбл

    # Accent-тинты (над бумагой) — чипы дат, выделения, зебра.
    "accent_12":    "#dae4e2",  # accent .12 — date-чип, выделение
    "accent_10":    "#dfe7e5",  # accent .10
    "accent_08":    "#e3e9e7",  # accent .08
    "accent_06":    "#e7ecea",  # accent .06

    # Таблицы.
    "table_zebra":  "#eaeeec",  # accent .045 — зебра
    "row_emph":     "#e7ecea",  # accent .06 — subtotal-строка
    "total_bg":     "#dfe7e5",  # accent .10 — total-строка
    "thead_line":   "#26706e",  # accent — линия под шапкой / total

    # Чипы (бронь / погода / TODO) — тинт-фон + рамка + тёмный fg.
    "chip_book_bg": "#dae4e2", "chip_book_fg": "#004b49", "chip_book_bd": "#a1bfbd",
    "chip_weather_bg": "#dbe1e5", "chip_weather_fg": "#204b70", "chip_weather_bd": "#afbfcc",
    "chip_todo_bg": "#e9e0d3", "chip_todo_fg": "#7b410f", "chip_todo_bd": "#d7bb9b",

    # Боксы warn / danger / info (левый edge + тинт + рамка).
    "box_warn_bg": "#ece5db", "box_warn_line": "#dbc4a9", "box_warn_edge": "#b57631",
    "box_danger_bg": "#ede3e0", "box_danger_line": "#ddb2ad", "box_danger_edge": "#b9473d",
    "box_info_bg": "#e2e7e8", "box_info_line": "#c0ccd5", "box_info_edge": "#4a6f93",

    # Stage 0 role badges (§4 «Stage 0 PDF»). Перекрасим в teal-семью отд. проходом.
    "role_core":        "#26706e",  # accent teal
    "role_supporting":  "#b57631",  # охра
    "role_niche":       "#7c3aed",  # muted purple
    "role_borderline":  "#7b410f",  # тёмная охра

    # Подсветки.
    "todo_highlight":     "#e9e0d3",  # warn .16 — фон TODO-чипа
    "warning_highlight":  "#ede3e0",  # danger .10 — фон warning
}

# Палитра для цветокодирования регионов (фидбэк-ревью 3.1): неяркие
# акценты, назначаются регионам по порядку появления. Тонкий маркер
# (полоса слева от плашки дня + caption-метка), не заливка.
REGION_PALETTE = [
    "#1a3a5c",  # тёмно-синий
    "#2d6a4f",  # приглушённо-зелёный (горы)
    "#b5651d",  # терракот (древние столицы)
    "#46688c",  # серо-голубой (море)
    "#9a6b3f",  # охра (традиционные/ремёсла)
    "#7c3aed",  # muted purple (запас)
    "#a13d3d",  # приглушённый красный (запас)
]


# ---------------------------------------------------------------------------
# Stage 3 палитра (категории POI + similarity + тон выдержек + флаги)
# ---------------------------------------------------------------------------
# Используется обоими рендерерами Stage 3 (PDF и DOCX) — accent-полоса
# слева у карточки, badge категории, цвет колонок coverage-таблицы.
# Категории фиксированы spec'ой stage3-poi.md §6 (6 значений).

# Цвета указаны БЕЗ префикса "#" — общее место для HexColor (reportlab)
# и RGBColor.from_string (python-docx). Конкретный рендерер сам префиксит.
CATEGORY_COLORS: dict[str, str] = {
    "STRONG CONFIRMED": "1a7f37",   # deep green
    "WEAK CONFIRMED":   "4d8b6d",   # muted green
    "HIDDEN GEM":       "7c3aed",   # purple
    "CONTESTED":        "d97706",   # amber
    "RED FLAG":         "b91c1c",   # danger red
    "LOW SIGNAL":       "6b7280",   # text-dim grey
}

# Короткие лейблы для badge на карточке и заголовков coverage-колонок.
# Ключ — space-EN категория (как в CATEGORY_COLORS), значение — РУССКИЙ
# badge-ярлык из taxonomy.json (SSOT переводов). Раньше были EN-аббревиатуры
# (STRONG/WEAK/…); теперь рендер бейджей русский без правок pdf/docx_lib.
CATEGORY_SHORT: dict[str, str] = {
    taxonomy.label("poi_category", _k, "en"): taxonomy.label("poi_category_badge", _k)
    for _k in taxonomy.keys("poi_category_badge")
}

# Similarity-категории из Stage 1 DR — для мини-чипа в атрибуции выдержки.
SIMILARITY_COLORS: dict[str, str] = {
    "HIGH":    "1a7f37",
    "OUTLIER": "7c3aed",
    "MEDIUM":  "3b6ea5",
    "LOW":     "6b7280",
}

# Stage 2 similarity-категории — заливка badge/рамки карточки в scoring-витрине
# (светлая тема PDF). С префиксом "#" (используется напрямую как accent_color
# в entity_card). LOW = красный (в витрине score красный сигнализирует мисматч),
# в отличие от серого LOW в SIMILARITY_COLORS (там — нейтральный chip Stage 3).
SIMILARITY_CARD_COLORS: dict[str, str] = {
    "HIGH":     "#1a7f37",   # green
    "OUTLIER":  "#7c3aed",   # purple
    "MEDIUM":   "#3b6ea5",   # blue
    "LOW":      "#b91c1c",   # red
    "UNSCORED": "#6b7280",   # grey
}

# Тон выдержки (✓/✗/•) на основании author stance из Stage 3 категоризации.
TONE_COLORS: dict[str, str] = {
    "pos": "1a7f37",   # ✓ green — рекомендует
    "neg": "b91c1c",   # ✗ red — критикует
    "neu": "6b7280",   # • grey — нейтрально / упоминает
}

# Флаги-чипы (combined_with / cluster / iconic_status / trap_archetype).
FLAG_COLORS: dict[str, str] = {
    "iconic_world":  "b08800",   # gold — iconic_status: world
    "iconic_other":  "9a7b3a",   # muted gold — national / regional iconic
    "trap":          "b91c1c",   # red — trap_archetype
    "cluster":       "3b6ea5",   # blue — cluster_id member
    "combined":      "5a6c87",   # slate — commonly_combined_with
    "exception":     "7c3aed",   # purple — iconic_exception
}


# ---------------------------------------------------------------------------
# Шрифты (export-design.md §5)
# ---------------------------------------------------------------------------

FONTS = {
    "heading":  "IBM Plex Sans",   # гуманистический гротеск — заголовки/дисплей
    "body":     "IBM Plex Sans",   # тот же гротеск — body (кириллица + ₽ ₩ € → ↔)
    "mono":     "IBM Plex Mono",   # monospace — числа (tnum), адреса, URL, бейджи
    # Реальные TTF-файлы забандлены в scripts/export/fonts/ (OFL). Геометрические
    # маркеры (▸ ▲ ● ○), которых нет в Plex, рендерятся через DejaVu-фолбэк
    # (FONT_SYM в pdf_lib). Хангыль/кандзи — Adobe CID-фонт reportlab.
    "heading_fallback": ["IBM Plex Sans", "DejaVu Sans", "sans-serif"],
    "body_fallback":    ["IBM Plex Sans", "DejaVu Sans", "sans-serif"],
    "mono_fallback":    ["IBM Plex Mono", "DejaVu Sans Mono", "monospace"],
}


# ---------------------------------------------------------------------------
# Размеры и layout (export-design.md §5)
# ---------------------------------------------------------------------------

# Типошкала перенесена из tokens.css (CSS px @96dpi → pt: ×0.75).
# Поля 48px → ~1.3 см (плотнее прежних 2 см — «modern guidebook»-плотность).
LAYOUT = {
    "margin_cm":              1.3,    # pad 48px ≈ 12.7 мм
    "line_height_body":       1.5,
    "line_height_heading":    1.2,
    # Размеры шрифтов в pt (px×0.75).
    "size_cover_title":       28.5,   # 38px — обложка
    "size_h1":                21,     # 28px — statband value
    "size_h2":                15,     # ~20px — крупный заголовок
    "size_h3":                12,     # 16px — title / day-title
    "size_title":             12,     # 16px — заголовок дня/секции-sub
    "size_sub":               10.5,   # 14px — подзаголовок обложки
    "size_body":              9.75,   # 13px — body
    "size_plate":             9.75,   # 13px — текст плашки секции (uppercase tracked)
    "size_small":             8.6,    # 11.5px — small
    "size_micro":             7.5,    # 10px — micro (метки, чипы, caption)
    # Page orientation per stage (§4).
    "stage0_orientation":     "landscape",  # coffee-table book layout
    "stage1_orientation":     "portrait",
    "stage3_orientation":     "portrait",
    "stage4_orientation":     "portrait",
    "stage5_orientation":     "portrait",
}


# ---------------------------------------------------------------------------
# Иконки (export-design.md §5)
# ---------------------------------------------------------------------------

# Маппинг emoji-маркеров из markdown в семантические иконки.
# Для PDF stage-модули могут заменить emoji на реальные image-иконки;
# для DOCX оставляем emoji как есть (Word рендерит ok).
ICON_MAP = {
    "📍": {"semantic": "location",  "lucide": "map-pin",  "alt": "Локация"},
    "🏨": {"semantic": "hotel",     "lucide": "bed",      "alt": "Отель"},
    "🎯": {"semantic": "activity",  "lucide": "target",   "alt": "Программа"},
    "💰": {"semantic": "budget",    "lucide": "wallet",   "alt": "Бюджет"},
    "⚠️": {"semantic": "warning",   "lucide": "triangle-alert", "alt": "Риски"},
    "⚠":  {"semantic": "warning",   "lucide": "triangle-alert", "alt": "Риски"},
    "⭐": {"semantic": "iconic",    "lucide": "star",     "alt": "Iconic"},
    "🔴": {"semantic": "red_flag",  "lucide": "flag",     "alt": "Red flag"},
}

# Маппинг тег-значений из Stage 3 (`обязательно / можно / не интересно`).
TAG_ICONS = {
    "обязательно":   {"lucide": "check-circle",  "color": COLORS["primary"]},
    "можно":         {"lucide": "help-circle",   "color": COLORS["secondary"]},
    "не интересно":  {"lucide": "x-circle",      "color": COLORS["danger"]},
}


# ---------------------------------------------------------------------------
# Role badges для Stage 0 cards (§4)
# ---------------------------------------------------------------------------

ROLE_BADGES = {
    "Core":       {"color": COLORS["role_core"],       "shape": "filled_circle"},
    "Supporting": {"color": COLORS["role_supporting"], "shape": "outline_circle"},
    "Niche":      {"color": COLORS["role_niche"],      "shape": "filled_diamond"},
    "Borderline": {"color": COLORS["role_borderline"], "shape": "dashed_circle"},
}

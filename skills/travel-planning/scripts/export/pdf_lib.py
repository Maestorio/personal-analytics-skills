"""pdf_lib.py — reportlab-обёртки для генерации PDF.

Зачем именно reportlab (а не weasyprint/Chrome):
  - pure Python, без native-deps (Cairo/Pango/etc.) — гарантированно
    ставится в любой sandbox через `pip install reportlab`;
  - Sonnet в облаке должен надёжно эту библиотеку запустить — без
    зависимости от системных бинарей пользователя;
  - reportlab — индустриальный стандарт, поддерживает кириллицу через
    регистрацию TTF, paragraphs, tables, flowables.

Этот модуль предоставляет:
  - `register_fonts()` — discovery Cyrillic-capable шрифтов на любой
    платформе (Linux DejaVu / macOS Arial Unicode / Helvetica.ttc);
  - `get_styles()` — ParagraphStyles, построенные из констант style.py;
  - `make_doc()` — фабрика SimpleDocTemplate с правильными margins
    под Stage 5 (portrait A4, см. layout в style.py);
  - helper-flowables: `cover_block`, `section_h2`, `section_h3`, `para`,
    `bullets`, `data_table`, `todo_span`, `warning_box`, `page_break`.

Stage-модули (stage5.py и далее) импортируют отсюда «лего», а не
работают с reportlab напрямую — это держит визуальный стиль централизованным.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Импорт reportlab — soft import, чтобы engine оставался импортируемым
# даже без reportlab (для unit-тестов parser/adapter без PDF-зависимости).
try:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, StyleSheet1
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        Flowable,
        Image,
        KeepTogether,
        ListFlowable,
        ListItem,
        CondPageBreak,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Базовый класс для BookmarkedDocTemplate. Без этой подстановки soft-import выше
# не работает: `class BookmarkedDocTemplate(SimpleDocTemplate)` — код уровня
# модуля, он выполняется независимо от REPORTLAB_AVAILABLE и падал с
# NameError. Из-за этого без reportlab не импортировался не только PDF-путь, но
# и HTML-экспорт Stage 6 (stages_html/stage6.py тянет stages/stage5,6 → pdf_lib
# ради констант фильтрации секций) — то есть «engine остаётся импортируемым»
# из докстроки было неправдой.
_DOC_BASE = SimpleDocTemplate if REPORTLAB_AVAILABLE else object

# style.py — соседний модуль того же пакета.
if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from export.style import (  # type: ignore[no-redef]
        COLORS, LAYOUT,
        CATEGORY_COLORS, CATEGORY_SHORT,
        FLAG_COLORS, TONE_COLORS, SIMILARITY_COLORS,
    )
else:
    from .style import (
        COLORS, LAYOUT,
        CATEGORY_COLORS, CATEGORY_SHORT,
        FLAG_COLORS, TONE_COLORS, SIMILARITY_COLORS,
    )


# ---------------------------------------------------------------------------
# Font discovery
# ---------------------------------------------------------------------------

# Имена внутри reportlab после регистрации (используются в стилях).
FONT_BODY = "TP-Body"
FONT_BODY_BOLD = "TP-BodyBold"
FONT_BODY_ITALIC = "TP-BodyItalic"
FONT_HEADING = "TP-Heading"
FONT_MONO = "TP-Mono"
FONT_MONO_BOLD = "TP-MonoBold"   # mono semibold — бейджи/итоги
FONT_CJK = "TP-CJK"   # шрифт с поддержкой CJK (хангыль/кандзи/ханьцзы)
FONT_SYM = "TP-Sym"   # symbol-фолбэк (DejaVu) для глифов, которых нет в Plex
                      # (геометрия ▸ ▲ ● ○ ☐ ☑ …)

# Unicode-блоки CJK, которые надо рендерить CJK-шрифтом, а не body.
# Корея (хангыль), Япония (хирагана/катакана/кандзи), Китай (ханьцзы).
_CJK_RANGES = (
    (0x1100, 0x11FF),    # Hangul Jamo
    (0x3040, 0x30FF),    # Hiragana + Katakana
    (0x3130, 0x318F),    # Hangul Compatibility Jamo
    (0x3400, 0x4DBF),    # CJK Ext A
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0xA960, 0xA97F),    # Hangul Jamo Extended-A
    (0xAC00, 0xD7AF),    # Hangul Syllables (경복궁 и т.д.)
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0xFF00, 0xFFEF),    # Halfwidth/Fullwidth Forms
)


def _is_cjk(cp: int) -> bool:
    """Принадлежит ли codepoint одному из CJK-блоков."""
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


@dataclass
class _FontFamily:
    """Описание одной семьи шрифта: пути к 4 начертаниям + alias."""
    label: str           # человекочитаемое имя для error message
    regular: str         # путь к regular TTF/TTC
    bold: str | None     # путь к bold (или None — синтезируем из regular)
    italic: str | None
    mono: str | None     # путь к moonspace для технических вставок
    ttc_index: int = 0   # для .ttc-коллекций (macOS Helvetica)


def _matplotlib_font_dir() -> str | None:
    """Найти путь к шрифтам, которые matplotlib bundle'ит с собой.

    matplotlib почти всегда присутствует в Python-средах с научным
    стеком (включая Anthropic sandbox), и он несёт DejaVu Sans / Mono
    в комплекте. Использовать его — самый надёжный кросс-платформенный
    способ получить шрифт с поддержкой кириллицы + ₽ + ⚠ без bundling
    в репозитории скилла.
    """
    try:
        import matplotlib  # type: ignore
        return os.path.join(os.path.dirname(matplotlib.__file__),
                            "mpl-data", "fonts", "ttf")
    except Exception:
        return None


def _make_candidates() -> list[_FontFamily]:
    """Сформировать список кандидатов с учётом matplotlib-пути."""
    candidates: list[_FontFamily] = []
    mpl = _matplotlib_font_dir()
    if mpl:
        candidates.append(_FontFamily(
            label="DejaVu (matplotlib)",
            regular=os.path.join(mpl, "DejaVuSans.ttf"),
            bold=os.path.join(mpl, "DejaVuSans-Bold.ttf"),
            italic=os.path.join(mpl, "DejaVuSans-Oblique.ttf"),
            mono=os.path.join(mpl, "DejaVuSansMono.ttf"),
        ))
    candidates.extend([
        # Linux: системный DejaVu (Anthropic sandbox обычно Linux).
        _FontFamily(
            label="DejaVu (system)",
            regular="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            italic="/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
            mono="/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ),
        # Linux: Liberation Sans (альтернатива DejaVu).
        _FontFamily(
            label="Liberation",
            regular="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            bold="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            italic="/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            mono="/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ),
        # macOS Arial Unicode — fallback. Внимание: не имеет ₽ U+20BD,
        # ⚠ U+26A0, em-dash и emoji — для таких символов делаем
        # substitution на render-уровне (см. `_substitute_missing_glyphs`).
        _FontFamily(
            label="macOS-Arial",
            regular="/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            bold=None,
            italic=None,
            mono="/System/Library/Fonts/Menlo.ttc",
        ),
        # macOS Helvetica.ttc — последний resort, ещё хуже с Cyrillic-coverage.
        _FontFamily(
            label="macOS-Helvetica",
            regular="/System/Library/Fonts/Helvetica.ttc",
            bold=None,
            italic=None,
            mono="/System/Library/Fonts/Menlo.ttc",
        ),
    ])
    return candidates


_FONT_CANDIDATES: list[_FontFamily] = _make_candidates()


# CJK-шрифты — Adobe CID-шрифты, встроенные в reportlab. НЕ требуют файла
# шрифта: PDF-вьюер сам подставляет подходящий CJK-фонт при отображении.
# Это решает проблему отсутствия CJK-файлов в Linux-sandbox и того, что
# macOS CJK-шрифты (AppleSDGothicNeo, Hiragino) используют PostScript/CFF
# outlines, которые reportlab.TTFont не поддерживает.
#
# Порядок предпочтения: корейский sans (под наши направления Корея/ЮВА),
# затем китайский/японский как fallback. Все покрывают Han-иероглифы;
# хангыль есть только в корейских.
_CJK_CID_FONTS = [
    "HYGothic-Medium",      # корейский sans-serif (хангыль + Han)
    "HYSMyeongJo-Medium",   # корейский serif (хангыль + Han)
    "STSong-Light",         # китайский (Han)
    "HeiseiKakuGo-W5",      # японский sans (кана + кандзи)
]


_FONTS_REGISTERED = False
_ACTIVE_FAMILY: str | None = None
_CJK_FAMILY: str | None = None     # label выбранного CJK-шрифта, None если нет
_CJK_FONT_NAME: str | None = None  # реальное имя для <font name=...> обёртки
# Множество codepoint'ов, которых нет в активном body-шрифте. Заполняется
# в register_fonts(). Используется в `_strip_unsupported_glyphs` для
# удаления символов, которые иначе рендерятся как ▢ (.notdef).
_UNSUPPORTED_CPS: set[int] = set()
# Symbol-фолбэк: имя зарегистрированного DejaVu-шрифта (или None) + множество
# codepoint'ов, которых нет в body-шрифте, НО есть в DejaVu (геометрия ▸▲●○
# ☐☑ …). Их не стрипаем — оборачиваем в FONT_SYM в `_wrap_symbol_runs`.
_SYM_FONT_NAME: str | None = None
_SYM_CPS: set[int] = set()


def _build_unsupported_set(face: Any) -> set[int]:
    """Просканировать «проблемные» диапазоны Unicode и собрать missing-set.

    Полностью таблицу не сканируем — это медленно. Проверяем эмодзи-блоки
    и стрелочные/символьные блоки, где DejaVu частично имеет покрытие.
    """
    ranges = [
        (0x2000, 0x27BF),    # Punctuation, Arrows, Math, Misc Symbols, Dingbats
        (0x2B00, 0x2BFF),    # Misc Symbols and Arrows (включая ⭐)
        (0x1F300, 0x1FAFF),  # Misc Symbols and Pictographs, Emoticons, и т.д.
        (0x1F000, 0x1F2FF),  # Mahjong/Domino/Card/Enclosed (мало встречаются)
    ]
    # CJK-блоки: их нет в DejaVu. Добавляем в скан, чтобы:
    #  - при наличии CJK-шрифта strip их пропустил (а _wrap_cjk_runs обернул);
    #  - при отсутствии — strip их выкинул (деградация без квадратов).
    ranges.extend(_CJK_RANGES)
    missing: set[int] = set()
    char_to_glyph = getattr(face, "charToGlyph", {})
    for lo, hi in ranges:
        for cp in range(lo, hi + 1):
            if char_to_glyph.get(cp, 0) == 0:
                missing.add(cp)
    return missing


def _plex_dir() -> str:
    """Путь к забандленным TTF IBM Plex (рядом со скриптом)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def _resolve_dejavu() -> str | None:
    """Найти DejaVuSans.ttf для symbol-фолбэка (геометрия ▸▲●○ ☐☑)."""
    cands = []
    mpl = _matplotlib_font_dir()
    if mpl:
        cands.append(os.path.join(mpl, "DejaVuSans.ttf"))
    cands.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def register_fonts() -> str:
    """Зарегистрировать шрифты в reportlab. Идемпотентно.

    Основная семья — забандленный IBM Plex Sans/Mono (OFL, `fonts/`):
    латиница + кириллица + ₽ ₩ € → ↔, табличные цифры. Если бандл недоступен
    — fallback на DejaVu/системные (legacy `_FONT_CANDIDATES`). Геометрические
    маркеры (▸ ▲ ● ○ ☐ ☑), которых нет в Plex, идут через DejaVu (`FONT_SYM`).
    Хангыль/кандзи — Adobe CID-фонт. Кидает RuntimeError, если нет даже body.
    """
    global _FONTS_REGISTERED, _ACTIVE_FAMILY
    if _FONTS_REGISTERED:
        return _ACTIVE_FAMILY or "unknown"
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "reportlab не установлен. Поставь через: "
            "pip install reportlab --break-system-packages"
        )

    pdir = _plex_dir()
    plex = {
        "reg":       os.path.join(pdir, "IBMPlexSans-Regular.ttf"),
        "ital":      os.path.join(pdir, "IBMPlexSans-Italic.ttf"),
        "semi":      os.path.join(pdir, "IBMPlexSans-SemiBold.ttf"),
        "bold":      os.path.join(pdir, "IBMPlexSans-Bold.ttf"),
        "mono":      os.path.join(pdir, "IBMPlexMono-Regular.ttf"),
        "mono_semi": os.path.join(pdir, "IBMPlexMono-SemiBold.ttf"),
    }
    if all(os.path.exists(p) for p in plex.values()):
        # Основной путь — забандленный IBM Plex.
        pdfmetrics.registerFont(TTFont(FONT_BODY, plex["reg"]))
        pdfmetrics.registerFont(TTFont(FONT_BODY_BOLD, plex["semi"]))   # 600
        pdfmetrics.registerFont(TTFont(FONT_BODY_ITALIC, plex["ital"]))
        pdfmetrics.registerFont(TTFont(FONT_HEADING, plex["bold"]))     # 700 — дисплей
        pdfmetrics.registerFont(TTFont(FONT_MONO, plex["mono"]))
        pdfmetrics.registerFont(TTFont(FONT_MONO_BOLD, plex["mono_semi"]))
        _ACTIVE_FAMILY = "IBM Plex"
    else:
        # Fallback: legacy-семьи (DejaVu/Liberation/системные).
        chosen: _FontFamily | None = None
        for fam in _FONT_CANDIDATES:
            if os.path.exists(fam.regular):
                chosen = fam
                break
        if chosen is None:
            searched = [f"{f.label}: {f.regular}" for f in _FONT_CANDIDATES]
            raise RuntimeError(
                "не нашёл шрифт с поддержкой кириллицы. Искал:\n  "
                + "\n  ".join(searched)
                + "\nЛибо положи IBM Plex TTF в fonts/, либо поставь DejaVu "
                "(Linux): apt-get install fonts-dejavu."
            )
        idx = chosen.ttc_index
        pdfmetrics.registerFont(TTFont(FONT_BODY, chosen.regular, subfontIndex=idx))
        if chosen.bold and os.path.exists(chosen.bold):
            pdfmetrics.registerFont(TTFont(FONT_BODY_BOLD, chosen.bold))
        else:
            pdfmetrics.registerFont(TTFont(FONT_BODY_BOLD, chosen.regular, subfontIndex=idx))
        if chosen.italic and os.path.exists(chosen.italic):
            pdfmetrics.registerFont(TTFont(FONT_BODY_ITALIC, chosen.italic))
        else:
            pdfmetrics.registerFont(TTFont(FONT_BODY_ITALIC, chosen.regular, subfontIndex=idx))
        pdfmetrics.registerFont(
            TTFont(FONT_HEADING, chosen.bold or chosen.regular, subfontIndex=idx))
        mono_path = chosen.mono if (chosen.mono and os.path.exists(chosen.mono)) else None
        pdfmetrics.registerFont(
            TTFont(FONT_MONO, mono_path or chosen.regular,
                   subfontIndex=0 if mono_path else idx))
        pdfmetrics.registerFont(
            TTFont(FONT_MONO_BOLD, mono_path or chosen.regular,
                   subfontIndex=0 if mono_path else idx))
        _ACTIVE_FAMILY = chosen.label

    # Привязка bold+italic в Paragraph-разметке (<b>, <i>).
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    registerFontFamily(
        FONT_BODY,
        normal=FONT_BODY,
        bold=FONT_BODY_BOLD,
        italic=FONT_BODY_ITALIC,
        boldItalic=FONT_BODY_BOLD,
    )

    # Symbol-фолбэк (DejaVu): геометрия ▸▲●○ ☐☑, которой нет в IBM Plex.
    global _SYM_FONT_NAME
    _SYM_FONT_NAME = None
    dejavu = _resolve_dejavu()
    if dejavu:
        try:
            pdfmetrics.registerFont(TTFont(FONT_SYM, dejavu))
            _SYM_FONT_NAME = FONT_SYM
        except Exception:
            _SYM_FONT_NAME = None

    # CJK-шрифт (хангыль/кандзи/ханьцзы) через Adobe CID-фонт reportlab.
    # CID-фонт регистрируется под своим реальным именем (например,
    # "HYGothic-Medium") — его и используем в `<font name=...>` обёртке.
    # Если ни один CID не доступен — CJK-символы стрипаются (деградация
    # без квадратов).
    global _CJK_FAMILY, _CJK_FONT_NAME
    _CJK_FAMILY = None
    _CJK_FONT_NAME = None
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        for cid_name in _CJK_CID_FONTS:
            try:
                pdfmetrics.registerFont(UnicodeCIDFont(cid_name))
                _CJK_FAMILY = cid_name
                _CJK_FONT_NAME = cid_name
                break
            except Exception:
                continue
    except Exception:
        pass

    # Соберём список codepoint'ов, которых нет в body-шрифте — для последующего
    # «вытирания» в md_inline_to_rl (иначе рендерится квадратиком .notdef).
    global _UNSUPPORTED_CPS, _SYM_CPS
    body_font = pdfmetrics.getFont(FONT_BODY)
    _UNSUPPORTED_CPS = _build_unsupported_set(body_font.face)

    # Из них — те, что есть в DejaVu (symbol-фолбэк): геометрия ▸▲●○ ☐☑ и пр.
    # Их НЕ стрипаем, а оборачиваем в FONT_SYM (`_wrap_symbol_runs`). Остальное
    # (эмодзи, которых нет даже в DejaVu) — стрипается.
    _SYM_CPS = set()
    if _SYM_FONT_NAME:
        sym_c2g = getattr(pdfmetrics.getFont(FONT_SYM).face, "charToGlyph", {})
        _SYM_CPS = {cp for cp in _UNSUPPORTED_CPS
                    if not _is_cjk(cp) and sym_c2g.get(cp, 0) != 0}

    _FONTS_REGISTERED = True
    return _ACTIVE_FAMILY or "unknown"


def _strip_unsupported_glyphs(text: str) -> str:
    """Удалить из текста codepoint'ы, которых нет в активном body-шрифте.

    Применяется в md_inline_to_rl. Без этого все emoji (📍/🏨/🎯/💰/⭐/📑
    и сотни других) рендерятся как ▢ — выглядит хуже, чем их отсутствие.
    Поддерживаемые в DejaVu символы (стрелки →↔, ⚠, ₽, ✓, ✈, •, ★ и т.п.)
    остаются нетронутыми.

    CJK-символы (хангыль/кандзи/ханьцзы) **не** стрипаются, если найден
    CJK-шрифт (`_CJK_FAMILY`) — они оборачиваются в `<font name=TP-CJK>`
    в `_wrap_cjk_runs`. Если CJK-шрифта нет — стрипаем (деградация без
    квадратов).

    Также удаляем variation selector U+FE0F (выбор цветного/моно варианта
    у эмодзи) — он визуально не нужен и иногда даёт лишний 0-width глиф.
    """
    if not _UNSUPPORTED_CPS and "️" not in text:
        return text
    out: list[str] = []
    for ch in text:
        cp = ord(ch)
        if ch == "️":          # variation selector U+FE0F
            continue
        if cp not in _UNSUPPORTED_CPS:
            out.append(ch)
            continue
        # cp не поддержан body-шрифтом. Оставляем, если:
        #  - есть symbol-фолбэк (DejaVu) с этим глифом (геометрия ▸▲●○ ☐☑) —
        #    обернётся в FONT_SYM в `_wrap_symbol_runs`;
        #  - это CJK и есть CJK-шрифт — обернётся в `_wrap_cjk_runs`.
        # Иначе (эмодзи без покрытия) — выкидываем.
        if cp in _SYM_CPS:
            out.append(ch)
        elif _CJK_FAMILY and _is_cjk(cp):
            out.append(ch)
    return "".join(out)


def _wrap_cjk_runs(text: str) -> str:
    """Обернуть максимальные последовательности CJK-символов в `<font name=TP-CJK>`.

    Вызывается в md_inline_to_rl ПОСЛЕ XML-escape, но осторожно: внутри
    уже могут быть теги (`<b>`, `<font>`, `<a>`). Поэтому работаем только
    с «голым» текстом между тегами — пропускаем всё внутри `<...>`.

    Если CJK-шрифт не зарегистрирован — no-op.
    """
    if not _CJK_FAMILY:
        return text

    out: list[str] = []
    i = 0
    n = len(text)
    in_tag = False
    run: list[str] = []

    def _flush_run() -> None:
        if run:
            out.append(f'<font name="{_CJK_FONT_NAME}">' + "".join(run) + "</font>")
            run.clear()

    while i < n:
        ch = text[i]
        if ch == "<":
            in_tag = True
            _flush_run()
            out.append(ch)
            i += 1
            continue
        if ch == ">":
            in_tag = False
            out.append(ch)
            i += 1
            continue
        if in_tag:
            out.append(ch)
            i += 1
            continue
        # Голый текст: CJK-символы копим в run, остальное — flush + append.
        if _is_cjk(ord(ch)):
            run.append(ch)
        else:
            _flush_run()
            out.append(ch)
        i += 1
    _flush_run()
    return "".join(out)


def _wrap_symbol_runs(text: str) -> str:
    """Обернуть символы из `_SYM_CPS` (геометрия ▸▲●○ ☐☑) в `<font name=TP-Sym>`.

    Тех глифов нет в IBM Plex, но есть в DejaVu. Логика идентична
    `_wrap_cjk_runs`: пропускаем содержимое `<...>`-тегов, копим run'ы
    fallback-символов и оборачиваем их. No-op, если symbol-фолбэк не найден.
    """
    if not _SYM_FONT_NAME or not _SYM_CPS:
        return text
    out: list[str] = []
    in_tag = False
    run: list[str] = []

    def _flush() -> None:
        if run:
            out.append(f'<font name="{_SYM_FONT_NAME}">' + "".join(run) + "</font>")
            run.clear()

    for ch in text:
        if ch == "<":
            in_tag = True
            _flush()
            out.append(ch)
            continue
        if ch == ">":
            in_tag = False
            out.append(ch)
            continue
        if in_tag:
            out.append(ch)
            continue
        if ord(ch) in _SYM_CPS:
            run.append(ch)
        else:
            _flush()
            out.append(ch)
    _flush()
    return "".join(out)


def sym(ch: str) -> str:
    """Завернуть литеральный symbol-глиф (▸ ▲ ● ☐ …) в FONT_SYM, если нужно.

    Для мест, где маркер вставляется напрямую в Paragraph-разметку (не через
    md_inline_to_rl) — например, чекбоксы bullet_list или маркеры боксов.
    """
    if _SYM_FONT_NAME and any(ord(c) in _SYM_CPS for c in ch):
        return f'<font name="{_SYM_FONT_NAME}">{ch}</font>'
    return ch


# ---------------------------------------------------------------------------
# ParagraphStyles
# ---------------------------------------------------------------------------


def get_styles() -> dict[str, "ParagraphStyle"]:
    """Вернуть набор ParagraphStyle'ов под Stage 5 (и переиспользуемых).

    Возвращает dict, чтобы stage-модули писали `styles["body"]` вместо
    индексной арифметики на StyleSheet1.
    """
    register_fonts()
    primary = HexColor(COLORS["primary"])
    text = HexColor(COLORS["text"])
    danger = HexColor(COLORS["danger"])
    warning = HexColor(COLORS["warning"])

    return {
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName=FONT_HEADING, fontSize=LAYOUT["size_cover_title"],
            leading=LAYOUT["size_cover_title"] * LAYOUT["line_height_heading"],
            textColor=primary, alignment=TA_LEFT, spaceAfter=24,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta",
            fontName=FONT_BODY, fontSize=14, leading=22,
            textColor=text, alignment=TA_LEFT, spaceAfter=8,
        ),
        "cover_subtitle": ParagraphStyle(
            "cover_subtitle",
            fontName=FONT_BODY, fontSize=13, leading=18,
            textColor=HexColor("#555555"), alignment=TA_LEFT, spaceAfter=18,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=FONT_HEADING, fontSize=LAYOUT["size_h2"],
            leading=LAYOUT["size_h2"] * LAYOUT["line_height_heading"],
            textColor=primary, alignment=TA_LEFT,
            spaceBefore=20, spaceAfter=12,
            keepWithNext=1,  # заголовок не остаётся один внизу страницы
        ),
        "h3": ParagraphStyle(
            "h3",
            fontName=FONT_HEADING, fontSize=LAYOUT["size_h3"],
            leading=LAYOUT["size_h3"] * LAYOUT["line_height_heading"],
            textColor=primary, alignment=TA_LEFT,
            spaceBefore=16, spaceAfter=8,
            keepWithNext=1,
        ),
        "h4": ParagraphStyle(
            "h4",
            fontName=FONT_HEADING, fontSize=13,
            leading=13 * LAYOUT["line_height_heading"],
            textColor=text, alignment=TA_LEFT,
            spaceBefore=10, spaceAfter=6,
            keepWithNext=1,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * LAYOUT["line_height_body"],
            # Выключка влево (ragged-right): полная выключка в узких колонках
            # и на длинных кириллических словах даёт «реки» межсловных пробелов.
            textColor=text, alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "body_compact": ParagraphStyle(
            "body_compact",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * 1.3,
            textColor=text, alignment=TA_LEFT,
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * LAYOUT["line_height_body"],
            textColor=text, alignment=TA_LEFT,
            leftIndent=16, bulletIndent=4, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=FONT_BODY, fontSize=LAYOUT["size_small"],
            leading=LAYOUT["size_small"] * 1.4,
            textColor=text,
        ),
        "warning_body": ParagraphStyle(
            "warning_body",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * LAYOUT["line_height_body"],
            textColor=danger, alignment=TA_LEFT,
            leftIndent=8, spaceAfter=4,
        ),
        "todo_inline": ParagraphStyle(
            "todo_inline",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * LAYOUT["line_height_body"],
            textColor=HexColor(COLORS["warning"]),
            backColor=HexColor(COLORS["todo_highlight"]),
            alignment=TA_LEFT,
            leftIndent=8, spaceAfter=4,
        ),
        "day_header": ParagraphStyle(
            "day_header",
            fontName=FONT_HEADING, fontSize=14,
            leading=14 * LAYOUT["line_height_heading"],
            textColor=primary, alignment=TA_LEFT,
            spaceBefore=14, spaceAfter=8,
            keepWithNext=True,
        ),
        "day_marker": ParagraphStyle(
            "day_marker",
            fontName=FONT_BODY, fontSize=LAYOUT["size_body"],
            leading=LAYOUT["size_body"] * LAYOUT["line_height_body"],
            textColor=text, alignment=TA_LEFT,
            leftIndent=0, spaceAfter=4,
        ),
    }


# ---------------------------------------------------------------------------
# Документ
# ---------------------------------------------------------------------------


class BookmarkedDocTemplate(_DOC_BASE):
    """SimpleDocTemplate, регистрирующий destination'ы и PDF-outline по
    реальной позиции flowable (каноничный reportlab-паттерн).

    Flowable-атрибуты:
      - `_dest_slug` — имя named destination. Регистрируется ВСЕГДА (для
        внутренних ссылок `<a href="#slug">`), даже если в outline не идёт.
      - `_outline_level` — если задан (0/1/...), дополнительно добавляется
        запись в PDF-outline (sidebar).
      - `_outline_title` — заголовок для outline (иначе getPlainText()).

    Почему здесь, а не через `<a name>`/AnchorFlowable: `<a name>` внутри
    ячейки Table даёт неверную Y, а отдельный 0-height anchor-flowable
    отрывается от плашки на page-break. afterFlowable вызывается ПОСЛЕ
    отрисовки flowable на его фактической странице — `self.frame._y`
    даёт точную позицию, bookmarkHorizontalAbsolute ставит dest туда.
    """

    def afterFlowable(self, flowable: Any) -> None:  # noqa: N802 (reportlab API)
        slug = getattr(flowable, "_dest_slug", None)
        if not slug:
            return
        # Верх только что отрисованного flowable на ТЕКУЩЕЙ странице.
        # `self.frame._y` — курсор после flowable (его низ); + высота = верх.
        # У Paragraph высота в `.height`, у Table — в `._height`/`_rowHeights`.
        h = getattr(flowable, "height", None)
        if not isinstance(h, (int, float)):
            h = getattr(flowable, "_height", None)
        if not isinstance(h, (int, float)) and getattr(flowable, "_rowHeights", None):
            h = sum(x for x in flowable._rowHeights if isinstance(x, (int, float)))
        if not isinstance(h, (int, float)):
            h = 0
        try:
            y_top = self.frame._y + h
            self.canv.bookmarkHorizontalAbsolute(slug, y_top)
        except Exception:
            self.canv.bookmarkPage(slug)
        level = getattr(flowable, "_outline_level", None)
        if level is not None:
            title = getattr(flowable, "_outline_title", None) or flowable.getPlainText()
            self.canv.addOutlineEntry(title, slug, level=level, closed=False)
            self.canv.showOutline()


def make_doc(
    output_path: str | Path,
    *,
    orientation: str = "portrait",
    title: str = "",
    author: str = "travel-planning",
    subject: str = "",
) -> "BookmarkedDocTemplate":
    """Создать DocTemplate с правильными margins + auto-outline.

    `subject` — служебный провенанс (из какого артефакта собран документ). Живёт
    в свойствах файла, а не на листе: читателю он не нужен, а восстановить
    происхождение PDF по нему можно."""
    register_fonts()
    pagesize = landscape(A4) if orientation == "landscape" else A4
    margin = LAYOUT["margin_cm"] * cm
    return BookmarkedDocTemplate(
        str(output_path),
        pagesize=pagesize,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title=title, author=author, subject=subject,
    )


# Текст футера (например, «создан 2026-05-28») — задаётся через
# set_footer_text() перед build_doc, рисуется слева в подвале.
_FOOTER_TEXT: str = ""


def set_footer_text(text: str) -> None:
    """Задать левый текст подвала на время рендера (сброс — пустой строкой)."""
    global _FOOTER_TEXT
    _FOOTER_TEXT = text or ""


def _draw_page_background(canvas: Any, doc: Any) -> None:
    """Page chrome: фон + accent-полоса сверху + footer (текст слева, № справа).

    Накладывается через `onFirstPage` / `onLaterPages` callback в build().
    """
    canvas.saveState()
    w, h = doc.pagesize
    # 1) Заливка фона — бумажный тёплый off-white.
    canvas.setFillColor(HexColor(COLORS["paper"]))
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # 2) Тонкая accent-полоса по верху.
    stripe_h = 3
    canvas.setFillColor(HexColor(COLORS["accent_stripe"]))
    canvas.rect(0, h - stripe_h, w, stripe_h, fill=1, stroke=0)
    # 3) Footer.
    margin = LAYOUT["margin_cm"] * cm
    canvas.setFillColor(HexColor(COLORS["muted"]))
    canvas.setFont(FONT_MONO, LAYOUT["size_micro"])
    if _FOOTER_TEXT:
        canvas.drawString(margin, margin * 0.5, _FOOTER_TEXT)
    canvas.drawRightString(w - margin, margin * 0.5, f"стр. {doc.page}")
    canvas.restoreState()


def build_doc(doc: "SimpleDocTemplate", story: list, *, with_background: bool = True) -> None:
    """Обёртка для doc.build с дефолтным cream-фоном и footer'ом."""
    if with_background:
        doc.build(
            story,
            onFirstPage=_draw_page_background,
            onLaterPages=_draw_page_background,
        )
    else:
        doc.build(story)


# ---------------------------------------------------------------------------
# Section anchors — internal links к H2-секциям внутри одного PDF
# ---------------------------------------------------------------------------

# Регистр anchors на время рендера одного документа. Заполняется
# stage-модулем перед началом рендера (set_section_anchors), очищается
# после (clear_section_anchors). Глобал ок — рендер один за раз.
_SECTION_ANCHORS: dict[str, str] = {}


def set_section_anchors(mapping: dict[str, str]) -> None:
    """Зарегистрировать anchor-карту heading → slug на время текущего рендера."""
    global _SECTION_ANCHORS
    _SECTION_ANCHORS = dict(mapping)


def clear_section_anchors() -> None:
    """Сбросить регистр anchor'ов (вызывать после build_doc)."""
    global _SECTION_ANCHORS
    _SECTION_ANCHORS = {}


if REPORTLAB_AVAILABLE:
    class AnchorFlowable(Flowable):
        """Невидимый flowable нулевой высоты, создающий named destination
        в ТОЧНОЙ позиции потока.

        Зачем: `<a name>` внутри ячейки Table (наши плашки дней/секций —
        это Table) reportlab привязывает к неверной Y-координате (низ
        страницы). Отдельный flowable на уровне story регистрирует
        destination через `canvas.bookmarkHorizontal` в реальной позиции,
        куда корректно ведут и внутренние ссылки, и PDF-outline.
        """
        def __init__(self, name: str):
            super().__init__()
            self.name = name
            self.width = 0
            self.height = 0

        def wrap(self, availWidth, availHeight):  # noqa: N802,N803
            return (0, 0)

        def draw(self):
            # На момент draw холст сдвинут в позицию flowable; (0,0) — его
            # нижний левый угол ≈ верх будущей плашки (она идёт следом).
            self.canv.bookmarkHorizontal(self.name, 0, 0)


def anchor(slug: str) -> "Flowable":
    """Вернуть невидимый anchor-flowable для точного destination в потоке."""
    return AnchorFlowable(slug)


def section_anchor_inline(slug: str) -> str:
    """XML-инлайн для anchor'а — встраивается в Paragraph header'а.

    После этой строки внутри Paragraph можно ссылаться `<a href="#slug">`.

    ReportLab's `<a name="...">` НЕ допускает content внутри — должен быть
    либо self-close (`<a name=".."/>`), либо явно пустой (`<a name=".."></a>`).
    Используем self-close — короче и одинаково работает.
    """
    return f'<a name="{slug}"/>'


def heading_paragraph(
    text: str,
    style: "ParagraphStyle",
    *,
    anchor_slug: str | None = None,
    outline_level: int | None = None,
) -> "Paragraph":
    """Paragraph для H2/H3 с опциональным якорем + outline entry.

    Чем отличается от `para()`:
      - НЕ прогоняет anchor XML через `md_inline_to_rl` (иначе `<a name>`
        экранируется и destination не регистрируется в PDF).
      - Если переданы `anchor_slug` + `outline_level` — Paragraph получает
        атрибуты `_outline_slug`/`_outline_title`/`_outline_level`, которые
        BookmarkedDocTemplate.afterFlowable превратит в PDF-outline entry
        (видимый в sidebar просмотрщика).
    """
    # Якорь НЕ встраиваем через `<a name>` — destination ставит afterFlowable
    # по реальной позиции (см. BookmarkedDocTemplate).
    p = Paragraph(md_inline_to_rl(text, highlight_todo=False), style)
    if anchor_slug:
        p._dest_slug = anchor_slug             # type: ignore[attr-defined]
        p._outline_title = text                # type: ignore[attr-defined]
        if outline_level is not None:
            p._outline_level = outline_level   # type: ignore[attr-defined]
    return p


def _link_known_subheading(tail: str) -> str:
    """В хвосте `## Section → Sub` слинковать известную под-секцию целым словом
    (предпочитая самое длинное совпадение). Ничего не нашли — хвост как есть.
    """
    if not tail.strip():
        return tail
    for known, kslug in sorted(_SECTION_ANCHORS.items(), key=lambda kv: -len(kv[0])):
        m = re.search(rf"(?<!\w){re.escape(known)}(?!\w)", tail)
        if m:
            return (tail[:m.start()] + f"\x00SLINK:{kslug}:{known}\x00"
                    + tail[m.end():])
    return tail


def preprocess_section_refs(text: str) -> str:
    """Заменить `` `## Heading` `` и `## Heading` на:
      - sentinel для будущего `<a href="#slug">Heading</a>`, если slug известен;
      - просто `Heading` (с удалением `## `), если секция не найдена в текущем
        документе (например, cross-stage ссылка `## Решение` из Stage 4).

    Sentinel-форма: `\\x00SLINK:slug:Heading\\x00` — пройдёт через XML escape
    нетронутой и развернётся в `<a>` тег в md_inline_to_rl (шаг после escape).
    """
    if not text:
        return text

    def _replace(match: "re.Match[str]") -> str:
        heading = match.group(1).strip()
        slug = _SECTION_ANCHORS.get(heading)
        if slug:
            return f"\x00SLINK:{slug}:{heading}\x00"
        # Точного совпадения нет. Возможно, после имени секции идёт хвост
        # (`## Сводные таблицы → Бюджет`): линкуем известный префикс, а в хвосте
        # — известную под-секцию (например «Бюджет» → таблица бюджета).
        for known, kslug in _SECTION_ANCHORS.items():
            if heading.startswith(known):
                tail = heading[len(known):]
                return f"\x00SLINK:{kslug}:{known}\x00" + _link_known_subheading(tail)
        return heading  # секция не из текущего файла — просто срезаем `## `

    # Сначала с обёрткой backticks `` `## Heading` ``, потом без.
    text = re.sub(r"`##\s+([^`\n]+?)`", _replace, text)
    text = re.sub(r"(?<!#)##\s+([А-ЯA-Zа-яa-z][^\n#]*?)(?=[.,;:)\]\s]|$)", _replace, text)
    return text


# ---------------------------------------------------------------------------
# Inline markup: md → reportlab Paragraph markup
# ---------------------------------------------------------------------------

# Reportlab Paragraph принимает упрощённую XML-разметку:
# <b>, <i>, <u>, <font color="#..">, <br/>, <a href="..">. Без <p>, <ul>, <li>.

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC_RE = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_CODE_RE = re.compile(r"`([^`\n]+)`")
# TODO-highlight: подсвечиваем ТОЛЬКО сам маркер, а не текст замечания —
# консистентно вне зависимости от того, как автор обернул маркер в md
# (`**TODO:**` / `TODO сверить на …` / `**TODO целое предложение.**`). Иначе
# спан подсветки «гулял» (граница `<b>`/`<a>`-тега обрезала его по-разному).
# Захватываем `TODO` плюс короткий квалификатор, ТОЛЬКО если он заканчивается
# двоеточием (`TODO за 2 недели:`); иначе — голое `TODO` (или `TODO.`).
# Прозаичный текст замечания (и ложные «TODO … нет») в highlight не попадают.
# Регистрозависимо: маркер всегда «TODO» в верхнем регистре. Так испанское
# «Todo Glaciares» и `todo` внутри URL (`.../todo-glaciares`) не подсвечиваются
# (а заодно не ломают XML, оборачивая текст внутри `<a href>`).
_TODO_INLINE_RE = re.compile(
    r"(\bTODO\b(?:[ \t][^\n:<]{1,30}:|:|\.)?)",
)


# Bare-URL автоконвертация — два паттерна:
#  1. URL со схемой `https://example.com/path` — однозначный.
#  2. Bare-domain без схемы `aerolineas.com.ar`, `cbr.ru` — частый случай в
#     stage5-источниках. Используем TLD-эвристику (`[a-z]{2,6}` + опц.
#     country code `.ar`/`.ru`/`.uk`/...) чтобы не цеплять «e.g.» и «etc.».
#
# Markdown-ссылки `[text](url)` обрабатываются раньше; чтобы НЕ заворачивать
# URL'ы, уже находящиеся внутри `<a href="...">…</a>`, мы вокруг bare-URL
# substitution применяем sentinel-обвёртку (см. md_inline_to_rl шаг 5).
_BARE_URL_RE = re.compile(
    r"(?<![\w/\(\"\>])"            # не часть уже существующей конструкции
    r"(https?://[^\s<>\)\]\"]+)"   # сам URL — стопаем на пробеле/тегах/скобках/кавычках
)
_BARE_DOMAIN_RE = re.compile(
    r"(?<![\w@/.\"\>])"                                # не часть word'а или href-атрибута
    r"("                                                # group 1: вся ссылка
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"          # один+ сегмент `word.`
    r"[a-z]{2,6}"                                       # TLD первого уровня (2-6 букв)
    r"(?:\.[a-z]{2,3})?"                                # опц. country-suffix (например, .com.ar)
    r"(?:/[\w\-./?=&%#~]*)?"                            # опц. путь
    r")"
    r"(?![\w@])",                                       # не часть word'а после
    re.IGNORECASE,
)
_EXISTING_ANCHOR_RE = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)


def _wrap_bare_urls(text: str) -> str:
    """Обернуть bare-URL/bare-domain в `<a>`-теги, не трогая уже-залинкованные.

    Алгоритм: вырезать существующие `<a>...</a>` в плейсхолдеры, применить
    URL-regex к остатку, восстановить anchors. Это спасает от двойной
    обёртки в markdown-link уже-конвертированных в `<a>` (`[text](url)`).
    """
    anchors: list[str] = []
    def _stash(m: "re.Match[str]") -> str:
        anchors.append(m.group(0))
        return f"\x00ANCHOR{len(anchors) - 1}\x00"
    masked = _EXISTING_ANCHOR_RE.sub(_stash, text)

    primary = COLORS["primary"]
    masked = _BARE_URL_RE.sub(
        rf'<a href="\1" color="{primary}"><u>\1</u></a>', masked,
    )
    masked = _BARE_DOMAIN_RE.sub(
        rf'<a href="https://\1" color="{primary}"><u>\1</u></a>', masked,
    )

    def _restore(m: "re.Match[str]") -> str:
        return anchors[int(m.group(1))]
    return re.sub(r"\x00ANCHOR(\d+)\x00", _restore, masked)


def md_inline_to_rl(text: str, *, highlight_todo: bool = True) -> str:
    """Преобразовать inline markdown к reportlab-разметке Paragraph.

    Применяется к ОДНОЙ строке/параграфу (без header'ов, без bullets).
    Если `highlight_todo` — оборачивает inline-TODO в `<font color="#...">`
    подсветку (для self-recipient это критично).

    Порядок преобразований важен:
      1. Strip unsupported glyphs (emoji, которых нет в шрифте) —
         делается на raw-тексте, ДО escape, потому что отметаем
         реальные codepoint'ы.
      2. Escape XML.
      3. Inline code (вводит первые `<font>` теги).
      4. Markdown links `[text](url)` → `<a>`.
      5. Bare URLs (которые ещё не в `<a>`) → `<a>`.
      6. Bold / italic.
      7. TODO highlight (последним, чтобы поверх всего).
    """
    if not text:
        return ""

    # Шаг 0: section-references → sentinel'ы. Делаем ДО escape — sentinel
    # содержит `\x00` который XML-escape не трогает, а `## ...` нам нужно
    # подцепить как raw markdown.
    text = preprocess_section_refs(text)

    # Шаг 0.5: снять markdown-escape `\$` → `$` (в источнике доллар
    # экранируется, чтобы reportlab не принял за спецсимвол; нам не нужно).
    text = text.replace("\\$", "$")

    # Шаг 1: убрать неподдерживаемые codepoint'ы.
    text = _strip_unsupported_glyphs(text)
    # Empty backticks `` `` остающиеся после strip эмодзи внутри inline-code
    # (например, `\`💰\`` → `\`\``) — выкидываем целиком, иначе они остаются
    # литералом и торчат в выводе.
    text = re.sub(r"`\s*`", "", text)

    # Шаг 2: escape XML.
    text = (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )
    # Шаг 3: inline code → <font name="mono">.
    text = _CODE_RE.sub(
        rf'<font name="{FONT_MONO}">\1</font>',
        text,
    )
    # Шаг 4: markdown ссылки.
    text = _LINK_RE.sub(
        rf'<a href="\2" color="{COLORS["primary"]}"><u>\1</u></a>',
        text,
    )
    # Шаг 5: bare URL → ссылка. Чтобы не оборачивать второй раз URL'ы,
    # уже находящиеся внутри только что вставленных `<a href="...">…</a>`,
    # вырезаем существующие `<a>...</a>` в sentinel-плейсхолдеры, обрабатываем
    # bare-URL, восстанавливаем.
    text = _wrap_bare_urls(text)
    # Шаг 6: bold / italic.
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)

    # Шаг 7: TODO-подсветка. Маркер всегда жирный — независимо от того, обернул
    # ли автор его в `**…**` в md (иначе вес «гулял»: то жирный, то обычный).
    # Вложенный <b> (если md уже сделал bold) reportlab переваривает.
    if highlight_todo:
        text = _TODO_INLINE_RE.sub(
            rf'<font color="{COLORS["warning"]}" backColor="{COLORS["todo_highlight"]}"><b>\1</b></font>',
            text,
        )

    # Шаг 8: восстановление section-link sentinel'ов из preprocess_section_refs.
    # Sentinel `\x00SLINK:slug:Heading\x00` пережил XML escape — теперь
    # подставляем настоящий `<a href="#slug">` (через XML-escape Heading'а).
    if "\x00SLINK:" in text:
        def _restore_slink(m: "re.Match[str]") -> str:
            slug = m.group(1)
            heading = m.group(2)
            heading_escaped = xml_escape(heading)
            return (
                f'<a href="#{slug}" color="{COLORS["primary"]}">'
                f'<u>{heading_escaped}</u></a>'
            )
        text = re.sub(r"\x00SLINK:([^:]+):([^\x00]+)\x00", _restore_slink, text)

    # Шаг 9: обернуть CJK-руны (хангыль/кандзи) в CJK-шрифт и symbol-руны
    # (геометрия ▸▲●○) в DejaVu-фолбэк. Делается последним — после всех
    # тегов, чтобы корректно пропускать `<...>`.
    text = _wrap_cjk_runs(text)
    text = _wrap_symbol_runs(text)

    return text


# ---------------------------------------------------------------------------
# Flowable-хелперы
# ---------------------------------------------------------------------------


def para(text: str, style: "ParagraphStyle", *, highlight_todo: bool = True) -> "Paragraph":
    """Paragraph с inline-разметкой md → reportlab."""
    return Paragraph(md_inline_to_rl(text, highlight_todo=highlight_todo), style)


def xml_escape(text: str) -> str:
    """Escape XML-спецсимволов для встраивания готового текста в Paragraph-разметку."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def lighten_hex(hex_color: str, factor: float = 0.6) -> str:
    """Осветлить hex-цвет, подмешав белый (factor 0..1, выше = светлее).

    Нужно для region-caption на тёмной плашке дня: тёмные региональные
    цвета (navy) на тёмном фоне нечитаемы — осветляем для контраста.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def labeled_para(
    label: str,
    body_md: str,
    style: "ParagraphStyle",
    *,
    color: str | None = None,
    highlight_todo: bool = True,
) -> "Paragraph":
    """Paragraph вида «**Label** body» с цветной меткой.

    Используется для day-markers (Локация / Отель / Программа / Бюджет /
    Риски) и для definition-list пунктов. Метка рендерится цветным жирным
    через `<font color="...">​<b>...</b></font>`. Пунктуация после метки
    (`.` или `:`) — обязанность caller'а (передаётся внутри `label`).
    Body — через `md_inline_to_rl` с TODO-подсветкой.
    """
    color = color or COLORS["primary"]
    label_xml = (
        f'<font color="{color}"><b>{xml_escape(label)}</b></font>'
    )
    body_xml = md_inline_to_rl(body_md, highlight_todo=highlight_todo) if body_md else ""
    sep = " " if body_xml else ""
    return Paragraph(f"{label_xml}{sep}{body_xml}", style)


def definition_list(
    items: list[tuple[str, str]],
    style: "ParagraphStyle",
    *,
    color: str | None = None,
    highlight_todo: bool = True,
) -> list["Paragraph"]:
    """Список пунктов вида «**Key:** value» как definition-list.

    Альтернатива bullet-list'у, когда источник имеет паттерн
    `- **Key:** value` подряд. Визуально читается лучше, чем bullets
    из-за того, что метки выровнены и не теряются среди ●-маркеров.
    """
    out: list[Paragraph] = []
    for key, val in items:
        out.append(labeled_para(
            f"{key}:", val, style, color=color, highlight_todo=highlight_todo,
        ))
    return out


# Markdown-checkbox: `- [ ] item` (empty) / `- [x] item` (checked).
_CHECKBOX_PREFIX_RE = re.compile(r"^\[([ xX])\]\s+(.*)$", re.DOTALL)


def bullet_list(items: list[str], styles: dict, *, highlight_todo: bool = True) -> list:
    """Bullet-list с inline-md разметкой. Возвращает СПИСОК флоувблов.

    Два режима:
      1. **Checkbox-список** (все пункты — markdown-checkbox `[ ] ...` или
         `[x] ...`): рендерим каждый как Paragraph с глифом ☐/☑ + nbsp и
         hanging-indent. ListFlowable не используем потому что reportlab
         «сжимает» пробел внутри bullet-маркера. С Paragraph + nbsp зазор
         между глифом и текстом гарантированно сохраняется.

      2. **Обычный bullet-список**: ListFlowable с `•` маркером.

    Callers должны делать `story.extend(bullet_list(...))`, не `.append(...)`.
    """
    cb_matches = [_CHECKBOX_PREFIX_RE.match(it.strip()) for it in items]
    all_checkbox = bool(items) and all(m is not None for m in cb_matches)

    if all_checkbox:
        # Hanging-indent: первая строка начинается с `[ ]` сразу,
        # последующие строки выравниваются после `[ ]`.
        cb_style = ParagraphStyle(
            "checkbox_item",
            parent=styles["bullet"],
            leftIndent=15,
            firstLineIndent=-15,
            spaceAfter=2,
        )
        paragraphs: list = []
        for m in cb_matches:
            # ☐ пустой / ☑ отмеченный (`[x]`) — типографски аккуратнее ASCII `[ ]`.
            # Глиф через FONT_SYM (DejaVu) — в IBM Plex его нет.
            mark = sym("☑" if m.group(1).lower() == "x" else "☐")  # type: ignore[union-attr]
            content = m.group(2).strip()                       # type: ignore[union-attr]
            body_xml = md_inline_to_rl(content, highlight_todo=highlight_todo)
            # `&nbsp;` × 2 = визуальный зазор между глифом и текстом без риска
            # того, что reportlab его «съест» при wrap.
            paragraphs.append(Paragraph(f"{mark}&nbsp;&nbsp;{body_xml}", cb_style))
        return paragraphs

    # Обычный bullet-list через ListFlowable. Маркер — ▸ (дизайн-язык) в
    # accent-цвете через FONT_SYM; graceful fallback на • в body-шрифте.
    use_tri = bool(_SYM_FONT_NAME) and ord("▸") in _SYM_CPS
    marker = "▸" if use_tri else "•"
    bullet_font = FONT_SYM if use_tri else FONT_BODY
    li_flowables = [
        ListItem(
            Paragraph(md_inline_to_rl(it, highlight_todo=highlight_todo), styles["bullet"]),
            leftIndent=14,
            bulletColor=HexColor(COLORS["accent"]),
        )
        for it in items
    ]
    return [ListFlowable(
        li_flowables,
        bulletType="bullet", start=marker,
        leftIndent=14, bulletFontName=bullet_font,
        bulletFontSize=LAYOUT["size_body"] - 1.5,
        bulletColor=HexColor(COLORS["accent"]),
    )]


def data_table(
    rows: list[list[str]],
    *,
    header: bool = True,
    col_widths: list[float] | None = None,
    highlight_todo: bool = True,
) -> "Table":
    """Таблица в стиле stage-артефактов (header — primary-цвет, body — серый).

    `rows[0]` — header, если `header=True`. Все ячейки проходят через
    md_inline_to_rl, поэтому **bold** / *italic* внутри ячейки работают.
    `col_widths` — список ширин в пунктах; None — равномерно по доступной ширине.
    """
    styles = get_styles()
    cell_style = styles["body_compact"]
    # Дизайн-язык .data-table: th — uppercase muted БЕЗ заливки, accent-линия
    # под шапкой; строки — hairline снизу; чётные строки тела — лёгкая зебра.
    header_style = ParagraphStyle(
        "table_header_cell", parent=cell_style,
        fontName=FONT_BODY, fontSize=LAYOUT["size_micro"],
        textColor=HexColor(COLORS["muted"]), alignment=TA_LEFT,
    )
    rendered = []
    for ridx, row in enumerate(rows):
        is_head = header and ridx == 0
        st = header_style if is_head else cell_style
        rendered.append([
            Paragraph(
                md_inline_to_rl((c or "").upper() if is_head else (c or ""),
                                highlight_todo=highlight_todo),
                st)
            for c in row
        ])
    table = Table(rendered, colWidths=col_widths, repeatRows=1 if header else 0)
    line = HexColor(COLORS["line"])
    ts = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_BODY),
        ("FONTSIZE", (0, 0), (-1, -1), LAYOUT["size_small"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, line),
    ]
    body_start = 1 if header else 0
    if header:
        ts.extend([
            ("LINEBELOW", (0, 0), (-1, 0), 2, HexColor(COLORS["accent"])),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ])
    for ridx in range(body_start, len(rows)):
        if (ridx - body_start) % 2 == 1:
            ts.append(("BACKGROUND", (0, ridx), (-1, ridx),
                       HexColor(COLORS["table_zebra"])))
    table.setStyle(TableStyle(ts))
    return table


def section_bar(
    text: str,
    *,
    anchor_slug: str | None = None,
    outline_level: int | None = None,
    bg_color: str | None = None,
) -> "Table":
    """Залитая плашка-заголовок H2-секции (белый текст на тёмном фоне).

    Визуальный якорь раздела — заметнее, чем просто цветной текст.
    Сохраняет anchor + PDF-outline через атрибуты на flowable
    (BookmarkedDocTemplate.afterFlowable их читает).

    `bg_color` — переопределить фон плашки (hex). Нужно для цветовой
    маркировки повторяющихся единиц (например, варианты маршрута Stage 4
    окрашиваются цветами REGION_PALETTE). None → дефолтный section_bar_bg.
    """
    register_fonts()
    # Якорь НЕ встраиваем в ячейку таблицы (дал бы неверную Y) — destination
    # ставит AnchorFlowable перед плашкой; здесь только outline-атрибуты.
    # Дизайн-язык `.section-plate`: uppercase semibold-заголовок на залитой
    # accent-плашке. Uppercase — на сыром тексте (до md→xml, чтобы не задеть теги).
    body = md_inline_to_rl(text.upper(), highlight_todo=False)
    style = ParagraphStyle(
        "section_bar_text",
        fontName=FONT_BODY_BOLD, fontSize=LAYOUT["size_plate"] + 1.25,
        leading=(LAYOUT["size_plate"] + 1.25) * 1.2,
        textColor=HexColor(COLORS["bar_text"]),
    )
    p = Paragraph(body, style)
    tbl = Table([[p]], colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg_color or COLORS["section_bar_bg"])),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    if anchor_slug:
        tbl._dest_slug = anchor_slug        # type: ignore[attr-defined]
        tbl._outline_title = text           # type: ignore[attr-defined]
        if outline_level is not None:
            tbl._outline_level = outline_level   # type: ignore[attr-defined]
    return tbl


def day_header_bar(
    date_label: str,
    title: str | None = None,
    *,
    anchor_slug: str | None = None,
    outline_level: int | None = None,
    region: str | None = None,        # сохранён для совместимости (не рендерится)
    region_color: str | None = None,
    transfer: bool = False,
) -> "Table":
    """Редакторская «лёгкая» шапка дня (дизайн-язык `.day`): date-чип + заголовок
    на бумаге (НЕ залитая плашка). Бюджет дня выносится в подвал (`day_budget_line`).

    `date_label` — «День N · дата» (рендерится как mono-чип).
    `title` — описательный заголовок дня; None → только чип.
    `transfer` — день-переезд: чип в охра-тинте + левая охра-полоса.
    `region_color` — опц. тонкая полоса слева цветом региона (если не переезд).
    """
    register_fonts()
    chip_fg = COLORS["chip_todo_fg"] if transfer else COLORS["accent_dark"]
    chip_bg = COLORS["chip_todo_bg"] if transfer else COLORS["accent_12"]
    chip = (f'<font name="{FONT_MONO}" size="{LAYOUT["size_micro"]}" '
            f'color="{chip_fg}" backColor="{chip_bg}">&nbsp;'
            f'{xml_escape(date_label.upper())}&nbsp;</font>')
    head_style = ParagraphStyle(
        "day_head_ed",
        fontName=FONT_BODY_BOLD, fontSize=LAYOUT["size_title"],
        leading=LAYOUT["size_title"] * 1.3,
        textColor=HexColor(COLORS["ink"]),
        spaceBefore=10, spaceAfter=2,
    )
    title_txt = (title or "").strip()
    if title_txt:
        para_xml = f'{chip}&nbsp;&nbsp;{md_inline_to_rl(title_txt, highlight_todo=False)}'
    else:
        para_xml = chip
    p = Paragraph(para_xml, head_style)
    tbl = Table([[p]], colWidths=["100%"])
    ts = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    # Переезд → левая охра-полоса; иначе опц. тонкая полоса цветом региона.
    rule = COLORS["warn"] if transfer else (region_color or None)
    if rule:
        ts.append(("LINEBEFORE", (0, 0), (0, -1), 3, HexColor(rule)))
        ts[1] = ("LEFTPADDING", (0, 0), (-1, -1), 10)
    tbl.setStyle(TableStyle(ts))
    if anchor_slug:
        tbl._dest_slug = anchor_slug        # type: ignore[attr-defined]
        tbl._outline_title = title_txt or date_label  # type: ignore[attr-defined]
        if outline_level is not None:
            tbl._outline_level = outline_level   # type: ignore[attr-defined]
    return tbl


def day_budget_line(budget_text: str) -> "Paragraph":
    """Подвал дня: «БЮДЖЕТ ДНЯ» (uppercase muted) + сумма mono ink."""
    register_fonts()
    text = re.sub(r"`\s*`", "", _strip_unsupported_glyphs(budget_text).strip())
    st = ParagraphStyle(
        "day_budget", fontName=FONT_BODY, fontSize=LAYOUT["size_micro"],
        leading=LAYOUT["size_micro"] * 1.5,
        textColor=HexColor(COLORS["muted"]), spaceBefore=4, spaceAfter=2,
    )
    amount = (f'<font name="{FONT_MONO}" size="{LAYOUT["size_small"]}" '
              f'color="{COLORS["ink"]}">{xml_escape(text)}</font>')
    return Paragraph(f"БЮДЖЕТ ДНЯ&nbsp;&nbsp;{amount}", st)


def region_titler(
    idx: int, total: int, name: str, meta: str, color: str,
    *,
    bullets: list[tuple[str, str]] | None = None,
    intro: str | None = None,
    anchor_slug: str | None = None,
) -> "Table":
    """Titler-блок региона перед днём входа.

    Структура (фидбэк-ревью 2.2):
        РЕГИОН N ИЗ M
        Название
        {опц. establishing-фраза — что это за регион и зачем в маршруте}
        Дни X–Y · даты · ночи · база
        • Главное: ...
        • Буфер: ...
        • Бронь заранее: ...
        • Риск: ...
        • Бюджет региона: ...

    `bullets` — список (label, value); каждый рендерится отдельной строкой
    с цветной жирной меткой. `intro` — короткая establishing-фраза региона
    (из поля `описание` маркера), курсивом под названием. Светлый блок с
    левой цветной полосой региона.
    """
    register_fonts()
    light_bg = lighten_hex(color, 0.85)
    cap_style = ParagraphStyle(
        "titler_cap", fontName=FONT_BODY_BOLD, fontSize=8, leading=11,
        textColor=HexColor(color),
    )
    name_style = ParagraphStyle(
        "titler_name", fontName=FONT_HEADING, fontSize=17, leading=21,
        textColor=HexColor(color), spaceBefore=2,
    )
    intro_style = ParagraphStyle(
        "titler_intro", fontName=FONT_BODY_ITALIC, fontSize=10, leading=14,
        textColor=HexColor(COLORS["text"]), spaceBefore=3, spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "titler_meta", fontName=FONT_BODY, fontSize=10, leading=14,
        textColor=HexColor(COLORS["text"]), spaceBefore=2, spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        "titler_bullet", fontName=FONT_BODY, fontSize=10, leading=14,
        textColor=HexColor(COLORS["text"]), spaceAfter=1,
    )
    cell = [
        Paragraph(f"РЕГИОН {idx} ИЗ {total}", cap_style),
        Paragraph(md_inline_to_rl(name, highlight_todo=False), name_style),
    ]
    if intro and intro.strip():
        cell.append(Paragraph(md_inline_to_rl(intro.strip(), highlight_todo=False), intro_style))
    if meta:
        cell.append(Paragraph(md_inline_to_rl(meta, highlight_todo=False), meta_style))
    for label, value in (bullets or []):
        line = (f'<font color="{color}"><b>{xml_escape(label)}:</b></font> '
                f'{md_inline_to_rl(value, highlight_todo=False)}')
        cell.append(Paragraph(line, bullet_style))
    inner = _stack(cell)
    tbl = Table([[inner]], colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(light_bg)),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor(color)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    # Только destination (для ссылок с имени региона в сводной таблице);
    # в PDF-outline titler НЕ добавляем.
    if anchor_slug:
        tbl._dest_slug = anchor_slug        # type: ignore[attr-defined]
    return tbl


def _stack(flowables: list) -> "Table":
    """Вертикальный стек flowables в одной ячейке (мини-таблица 1 колонка)."""
    tbl = Table([[f] for f in flowables], colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return tbl


def _format_budget_bar(budget_text: str) -> str:
    """Разметка бюджета для правого угла плашки дня.

    Сумму ₩ — белым bold, конвертацию в скобках (₽) — приглушённым белым.
    Пример входа: «~₩40 000–60 000 (~2 800–4 100 ₽)».
    """
    text = _strip_unsupported_glyphs(budget_text).strip()
    text = re.sub(r"`\s*`", "", text)
    # Разбиваем на основную часть и скобочную конвертацию.
    m = re.match(r"^(.*?)\s*(\([^)]*₽[^)]*\))\s*$", text)
    dim = COLORS["bar_text_dim"]
    if m:
        main = xml_escape(m.group(1).strip())
        conv = xml_escape(m.group(2).strip())
        return f'<b>{main}</b> <font color="{dim}">{conv}</font>'
    return f"<b>{xml_escape(text)}</b>"


def key_params_table(rows: list[tuple[str, str]]) -> "Table":
    """Двухколоночная таблица «Параметр | Значение» для обложки.

    Заметно удобнее списка для сканирования (фидбэк-ревью 2.1).
    Левая колонка — bold-метки, правая — значения (с inline-md).
    """
    styles = get_styles()
    # Дизайн-язык `.passport`: верхняя ink-линия + hairline-строки, без рамки
    # и зебры. Метки — uppercase micro muted; значения — body ink.
    label_style = ParagraphStyle(
        "kp_label", parent=styles["body_compact"],
        fontName=FONT_BODY, fontSize=LAYOUT["size_micro"],
        leading=LAYOUT["size_micro"] * 1.3,
        textColor=HexColor(COLORS["muted"]),
    )
    value_style = ParagraphStyle(
        "kp_value", parent=styles["body_compact"],
        textColor=HexColor(COLORS["ink"]),
    )
    data = [
        [Paragraph(xml_escape(k).upper(), label_style),
         Paragraph(md_inline_to_rl(v, highlight_todo=False), value_style)]
        for k, v in rows
    ]
    tbl = Table(data, colWidths=["27%", "73%"])
    ts = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        # Верхняя ink-линия (паспорт-рамка) + hairline под каждой строкой.
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, HexColor(COLORS["ink"])),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor(COLORS["line"])),
    ]
    tbl.setStyle(TableStyle(ts))
    return tbl


def _box_mark_prefix(mark: str, color: str) -> str:
    """Inline-маркер бокса (▲ / ●) в FONT_SYM нужного цвета + зазор.

    Пусто, если symbol-фолбэк недоступен или глиф не из его набора
    (graceful — без .notdef-квадрата).
    """
    if _SYM_FONT_NAME and all(ord(c) in _SYM_CPS for c in mark):
        return f'<font name="{_SYM_FONT_NAME}" color="{color}">{mark}</font>&nbsp;&nbsp;'
    return ""


def _box(
    body: "list | str", *, edge: str, bg: str, line: str,
    mark: str, mark_color: str, text_color: str | None = None,
) -> "Table":
    """Универсальный бокс дизайн-языка `.box`: левый цветной edge + тинт-фон +
    hairline-рамка + inline-маркер (▲ warn/danger, ● info).

    `body` — строка (один Paragraph) или список flowable'ов (bullets/стек).
    """
    register_fonts()
    if isinstance(body, str):
        st = ParagraphStyle(
            "box_text", fontName=FONT_BODY, fontSize=LAYOUT["size_body"] - 0.5,
            leading=(LAYOUT["size_body"] - 0.5) * 1.45,
            textColor=HexColor(text_color or COLORS["text"]),
        )
        prefix = _box_mark_prefix(mark, mark_color)
        inner: Any = Paragraph(prefix + md_inline_to_rl(body, highlight_todo=False), st)
    else:
        inner = body[0] if len(body) == 1 else _stack(body)
    tbl = Table([[inner]], colWidths=["100%"])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg)),
        ("LINEBEFORE", (0, 0), (0, -1), 3, HexColor(edge)),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor(line)),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return tbl


def warning_box(text: str, styles: dict) -> "Table":
    """Warning-бокс `.box--warn`: левый охра-edge + тинт-фон + ▲ маркер.

    Дневные «Риски» и сезонные предупреждения — заметный, но не кричащий блок.
    """
    return _box(
        text, edge=COLORS["box_warn_edge"], bg=COLORS["box_warn_bg"],
        line=COLORS["box_warn_line"], mark="▲", mark_color=COLORS["warn"],
        text_color=COLORS["warn_text"],
    )


def warning_box_bullets(items: list[str], styles: dict) -> "Table":
    """Warning-box с bullet-list'ом внутри — вместо N отдельных warning_box'ов.

    Стиль идентичен `warning_box` (amber-фон + amber-граница, тёмно-янтарный
    текст), но контент — bullet-список, не одиночный параграф. Полезно для
    сводки warning'ов в одном визуальном блоке (Stage 1: META-DIAGNOSTICS
    WARNs; в будущем — pre-emit warnings Stage 5).
    """
    register_fonts()
    items = [it for it in items if it and it.strip()]
    if not items:
        return Table([[""]], colWidths=["100%"])
    warn_style = ParagraphStyle(
        "warn_box_bullet",
        fontName=FONT_BODY, fontSize=LAYOUT["size_body"] - 0.5,
        leading=(LAYOUT["size_body"] - 0.5) * 1.45,
        textColor=HexColor(COLORS["warn_text"]),
        leftIndent=12, firstLineIndent=-10, spaceAfter=2,
    )
    bullet_color = COLORS["warn"]
    paragraphs: list = []
    for it in items:
        text = md_inline_to_rl(it.strip(), highlight_todo=False)
        paragraphs.append(Paragraph(
            f'<font color="{bullet_color}">•</font>&nbsp;{text}',
            warn_style,
        ))
    return _box(
        paragraphs, edge=COLORS["box_warn_edge"], bg=COLORS["box_warn_bg"],
        line=COLORS["box_warn_line"], mark="▲", mark_color=COLORS["warn"],
    )


def info_box(text: str, styles: dict) -> "Table":
    """Нейтральная info-note: светло-голубой фон + левая акцент-полоса.

    Это НЕ warning (для рисков есть warning_box с amber-рамкой). Info-note —
    спокойная пояснительная заметка (например, что значит 💰 в днях).
    """
    return _box(
        text, edge=COLORS["box_info_edge"], bg=COLORS["box_info_bg"],
        line=COLORS["box_info_line"], mark="●", mark_color=COLORS["info"],
    )


def status_chips(chips: list[tuple[str, str, str]]) -> "Paragraph | None":
    """Строка статус-чипов из `(label, fg_hex, bg_hex)` → один Paragraph.

    Цветной фон через `<font backColor>` (chip-эффект). Используется для
    статус-маркеров дня Stage 5 (бронь / погода). None, если список пуст.
    """
    chips = [c for c in chips if c and c[0]]
    if not chips:
        return None
    style = ParagraphStyle(
        "status_chips",
        fontName=FONT_BODY, fontSize=LAYOUT["size_small"],
        leading=LAYOUT["size_small"] * 1.7,
        spaceBefore=1, spaceAfter=4,
    )
    parts = []
    for label, fg, bg in chips:
        txt = xml_escape(label)
        parts.append(f'<font color="{fg}" backColor="{bg}">&nbsp;{txt}&nbsp;</font>')
    return Paragraph("&nbsp;&nbsp;".join(parts), style)


def cover_kicker(text: str) -> "Paragraph":
    """Кикер обложки: accent uppercase micro над заголовком (дизайн-язык .cover-kicker)."""
    register_fonts()
    st = ParagraphStyle(
        "cover_kicker", fontName=FONT_BODY_BOLD, fontSize=LAYOUT["size_micro"],
        leading=LAYOUT["size_micro"] * 1.4,
        textColor=HexColor(COLORS["accent"]), spaceAfter=5,
    )
    return Paragraph(xml_escape(text).upper(), st)


def stat_band(stats: list[tuple[str, str, str]]) -> "Table":
    """Статбенд обложки (дизайн-язык .statband): ряд крупных показателей —
    uppercase-метка сверху, большое значение + unit снизу; верхняя ink-линия
    и вертикальные hairline-разделители. `stats` = [(label, value, unit), …]."""
    register_fonts()
    stats = [s for s in stats if s and s[1]]
    if not stats:
        return Table([[""]], colWidths=["100%"])
    label_st = ParagraphStyle(
        "statband_k", fontName=FONT_BODY, fontSize=LAYOUT["size_micro"],
        leading=LAYOUT["size_micro"] * 1.3, textColor=HexColor(COLORS["muted"]),
        alignment=TA_CENTER, spaceAfter=4,
    )
    val_st = ParagraphStyle(
        "statband_v", fontName=FONT_HEADING, fontSize=18, leading=21,
        textColor=HexColor(COLORS["ink"]), alignment=TA_CENTER,
    )
    cells = []
    for label, value, unit in stats:
        v = f'<font name="{FONT_HEADING}" size="18">{xml_escape(value)}</font>'
        if unit:
            v += (f' <font name="{FONT_BODY}" size="10" '
                  f'color="{COLORS["muted"]}">{xml_escape(unit)}</font>')
        cells.append(_stack([
            Paragraph(xml_escape(label).upper(), label_st),
            Paragraph(v, val_st),
        ]))
    n = len(stats)
    tbl = Table([cells], colWidths=[f"{100 / n:.4f}%"] * n)
    ts = [
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, HexColor(COLORS["ink"])),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor(COLORS["line"])),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(n - 1):
        ts.append(("LINEAFTER", (i, 0), (i, 0), 0.5, HexColor(COLORS["line"])))
    tbl.setStyle(TableStyle(ts))
    return tbl


if REPORTLAB_AVAILABLE:
    class _RouteRibbon(Flowable):
        """Лента маршрута (дизайн-язык .ribbon): точки баз на горизонтальной
        accent-линии + подпись и под-метка (ночи). Концы — ink, промежуточные —
        accent. Рисуется на canvas (линия + круги + центрированный текст)."""

        def __init__(self, stops: list[tuple[str, str]], height: float = 56):
            super().__init__()
            self.stops = [s for s in stops if s and s[0]]
            self.height = height
            self.width = 0

        def wrap(self, availWidth, availHeight):  # noqa: N802,N803
            self.width = availWidth
            return (availWidth, self.height)

        def draw(self):
            register_fonts()
            c = self.canv
            stops = self.stops
            n = len(stops)
            if n == 0:
                return
            m = 12
            usable = self.width - 2 * m
            line_y = self.height - 12
            xs = [m + (usable * i / (n - 1) if n > 1 else usable / 2) for i in range(n)]
            if n > 1:
                c.saveState()
                c.setStrokeColor(HexColor(COLORS["accent"]))
                c.setLineWidth(2)
                c.setLineCap(1)
                c.setStrokeAlpha(0.4)
                c.line(xs[0], line_y, xs[-1], line_y)
                c.restoreState()
            for i, (name, sub) in enumerate(stops):
                x = xs[i]
                is_end = (i == 0 or i == n - 1)
                c.setFillColor(HexColor(COLORS["ink"] if is_end else COLORS["accent"]))
                c.circle(x, line_y, 5, fill=1, stroke=0)
                c.setFillColor(HexColor(COLORS["ink"]))
                c.setFont(FONT_BODY_BOLD, 8.5)
                c.drawCentredString(x, line_y - 18, name)
                if sub:
                    c.setFillColor(HexColor(COLORS["muted"]))
                    c.setFont(FONT_MONO, 7)
                    c.drawCentredString(x, line_y - 29, sub)


def route_ribbon(stops: list[tuple[str, str]]) -> "Flowable":
    """Лента маршрута для обложки. `stops` = [(имя_базы, под-метка), …]."""
    register_fonts()
    return _RouteRibbon(stops)


def spacer(height_pt: float = 6) -> "Spacer":
    """Вертикальный spacer."""
    return Spacer(1, height_pt)


def page_break() -> "PageBreak":
    """Принудительный page break."""
    return PageBreak()


def cond_page_break(min_space: float) -> "CondPageBreak":
    """Разрыв, срабатывающий только если до низа листа осталось < `min_space`.

    В отличие от `page_break()` не создаёт полупустых страниц: короткая секция
    садится на текущий лист, если там есть куда. Это `Spacer`, а не `PageBreak`,
    поэтому `_collapse_double_breaks` его не видит — и правильно: подряд идущие
    условные разрывы пустых страниц не порождают."""
    return CondPageBreak(min_space)


def content_box() -> tuple[float, float]:
    """Доступная под контент область страницы (portrait A4) в пунктах."""
    margin = LAYOUT["margin_cm"] * cm
    return A4[0] - 2 * margin, A4[1] - 2 * margin


def map_image(png_path: str | Path, *, max_height_frac: float = 0.82) -> "Image":
    """Встроить PNG-карту (matplotlib → reportlab Image), вписав в страницу.

    Масштабируется по ширине контент-области с сохранением пропорций; если по
    высоте не помещается (карта вытянута), ужимается по высоте. Центрируется.
    `max_height_frac` — доля высоты контент-бокса под карту (оставляем место
    под плашку-заголовок и подпись).
    """
    avail_w, avail_h = content_box()
    avail_h *= max_height_frac
    iw, ih = ImageReader(str(png_path)).getSize()
    scale = min(avail_w / iw, avail_h / ih)
    img = Image(str(png_path), width=iw * scale, height=ih * scale)
    img.hAlign = "CENTER"
    return img


# ---------------------------------------------------------------------------
# Универсальная entity-card (карточка сущности)
# ---------------------------------------------------------------------------
#
# Общий примитив для карточек регионов (Stage 0), DR-отчётов (Stage 1),
# авторов (Stage 2), POI (Stage 3 — для DOCX-ветки потом будет своя
# реализация в docx_lib). Слоты:
#
#   title          — имя сущности (крупно)
#   accent_color   — цвет полосы слева + тинт фона
#   badge          — (text, color) в правом верхнем углу (роль/категория/trust)
#   meta_line      — компактная строка под header (density · season · ...)
#   body           — markdown-описание (inline-md поддерживается)
#   side_badges    — список (text, color) дополнительных меток внизу
#   title_link     — URL, оборачивает title в кликабельную ссылку
#                    (используется в Stage 0 для Google Images по региону)
#
# Stage-модуль не строит карточку напрямую — он мапит свои поля на эти
# слоты через тонкий wrapper (например, `_region_to_card`).


def entity_card(
    *,
    title: str,
    accent_color: str,
    badge: tuple[str, str] | None = None,
    meta_line: str | None = None,
    body: str | None = None,
    body_bullets: list[str] | None = None,
    colored_lines: list[tuple[str, str, str]] | None = None,
    side_badges: list[tuple[str, str]] | None = None,
    title_link: str | None = None,
    anchor_slug: str | None = None,
    width: str | float = "100%",
) -> "Table":
    """Карточка сущности — общий примитив для cards-вёрстки.

    Структура:
      ┌────────────────────────────────────┐
      │ ▎title (опц. ссылка)       [BADGE] │  ← header row
      │ ▎meta_line (small, muted)          │
      │ ▎body (1–3 параграфа inline-md)    │
      │ ▎[chip1] [chip2] [chip3]           │  ← side_badges row (опц.)
      └────────────────────────────────────┘
        ↑ цветная полоса слева (accent_color, 4pt)
        фон — мягкий тинт accent_color (lighten 90%)
    """
    register_fonts()

    tint = lighten_hex(accent_color, 0.90)
    title_color = accent_color

    # — Header row: title (слева) + badge (справа), 2-колоночная inner-table.
    title_style = ParagraphStyle(
        "card_title",
        fontName=FONT_HEADING, fontSize=14, leading=17,
        textColor=HexColor(title_color), alignment=TA_LEFT,
    )
    title_text = title
    if title_link:
        title_text = f"[{title}]({title_link})"
    title_p = Paragraph(md_inline_to_rl(title_text, highlight_todo=False), title_style)

    header_cells: list = [title_p]
    if badge:
        badge_text, badge_color = badge
        badge_style = ParagraphStyle(
            "card_badge",
            # 7pt (не 8): «SUPPORTING»/«BORDERLINE» при 8pt не влезали в
            # ячейку 60pt и ломались посреди слова («SUPPORTI NG»).
            fontName=FONT_BODY_BOLD, fontSize=7, leading=10,
            textColor=HexColor(COLORS["background"]),
            alignment=TA_CENTER,
        )
        badge_p = Paragraph(xml_escape(badge_text.upper()), badge_style)
        badge_cell = Table([[badge_p]], colWidths=[60])
        badge_cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor(badge_color)),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROUNDEDCORNERS", [2, 2, 2, 2]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        header_cells = [title_p, badge_cell]

    if badge:
        header_table = Table([header_cells], colWidths=["75%", "25%"])
        header_table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (0, -1), "TOP"),
            ("VALIGN", (1, 0), (1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        cell_flow: list = [header_table]
    else:
        cell_flow = [title_p]

    # — Meta line.
    if meta_line:
        meta_style = ParagraphStyle(
            "card_meta",
            fontName=FONT_BODY, fontSize=8.5, leading=12,
            textColor=HexColor("#5b6b7e"),
            spaceBefore=2, spaceAfter=4,
        )
        cell_flow.append(Paragraph(
            md_inline_to_rl(meta_line, highlight_todo=False), meta_style,
        ))

    # — Body. Два режима: bullets (приоритет) ИЛИ параграфы.
    body_style = ParagraphStyle(
        "card_body",
        fontName=FONT_BODY, fontSize=10.5, leading=14,
        textColor=HexColor(COLORS["text"]),
        alignment=TA_LEFT, spaceAfter=3,
    )
    if body_bullets:
        # bullet-список с компактным маркером, hanging-indent.
        bullet_style = ParagraphStyle(
            "card_bullet",
            parent=body_style, leftIndent=12, firstLineIndent=-10,
            spaceAfter=2,
        )
        for item in body_bullets:
            if not item or not item.strip():
                continue
            text = md_inline_to_rl(item.strip(), highlight_todo=False)
            cell_flow.append(Paragraph(
                f'<font color="{accent_color}">•</font>&nbsp;{text}',
                bullet_style,
            ))
    elif body and body.strip():
        for para_text in body.strip().split("\n\n"):
            para_text = para_text.strip()
            if not para_text:
                continue
            cell_flow.append(Paragraph(
                md_inline_to_rl(para_text, highlight_todo=False), body_style,
            ))

    # — Colored lines (опц.): строки с цветной bold-меткой + обычным текстом.
    # Каждая — (label, text, hex_color). Метка красится в color, текст —
    # обычным цветом тела. Используется для «Тянет вверх» (green) / «Тянет
    # вниз» (red) / «SIGNAL» (purple) в карточках Stage 2.
    if colored_lines:
        cl_style = ParagraphStyle(
            "card_colored_line",
            fontName=FONT_BODY, fontSize=10, leading=13.5,
            textColor=HexColor(COLORS["text"]),
            alignment=TA_LEFT, spaceBefore=2, spaceAfter=2,
        )
        for label, text, color in colored_lines:
            if not text or not str(text).strip():
                continue
            label_html = (f'<font color="{color}"><b>{xml_escape(label)}</b></font> '
                          if label else "")
            body_html = md_inline_to_rl(str(text), highlight_todo=False)
            cell_flow.append(Paragraph(label_html + body_html, cl_style))

    # — Side badges (опц.): маленькие цветные chip'ы внизу.
    if side_badges:
        chips: list = []
        for text, color in side_badges:
            chip_style = ParagraphStyle(
                f"card_chip_{len(chips)}",
                fontName=FONT_BODY_BOLD, fontSize=7.5, leading=10,
                textColor=HexColor(color),
                alignment=TA_LEFT,
            )
            chip_p = Paragraph(xml_escape(text.upper()), chip_style)
            chip_cell = Table([[chip_p]])
            chip_cell.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), HexColor(lighten_hex(color, 0.85))),
                ("BOX", (0, 0), (-1, -1), 0.4, HexColor(color)),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            chips.append(chip_cell)
        # Раскладываем chips в одну строку через горизонтальную Table.
        chips_row = Table([chips], colWidths=[None] * len(chips))
        chips_row.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        cell_flow.append(Spacer(1, 3))
        cell_flow.append(chips_row)

    inner = _stack(cell_flow)
    tbl = Table([[inner]], colWidths=[width] if isinstance(width, str) else [width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(tint)),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor(accent_color)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    if anchor_slug:
        tbl._dest_slug = anchor_slug   # type: ignore[attr-defined]
    return tbl


def card_grid(cards: list["Table"], *, cols: int = 2, gutter_pt: float = 8) -> "Table":
    """Раскладывает entity_card'ы в N-колоночную сетку.

    Реализация: outer Table с `cols` колонок и ceil(N/cols) рядов;
    промежуток между колонками задаётся через LEFTPADDING/RIGHTPADDING ячеек.
    Пустые позиции (когда N % cols != 0) заполняются пустыми Spacer'ами.
    """
    if not cards:
        return Table([[""]])
    rows: list[list] = []
    for i in range(0, len(cards), cols):
        chunk = cards[i:i + cols]
        # Дозаполняем пустыми ячейками, чтобы у Table была регулярная сетка.
        while len(chunk) < cols:
            chunk.append(Spacer(1, 1))
        rows.append(chunk)

    # Колонки — равной ширины: "{100/cols}%" каждая.
    col_pct = f"{int(100 / cols)}%"
    col_widths = [col_pct] * cols
    tbl = Table(rows, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), gutter_pt / 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), gutter_pt / 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), gutter_pt),
    ]))
    return tbl


# ---------------------------------------------------------------------------
# Stage 3 POI card / cluster header — собственная карточка с тонами выдержек
# ---------------------------------------------------------------------------

def poi_card(
    *,
    num: int,
    name_ru: str,
    name_local: str,
    category: str,
    counts_line: str,
    excerpts: list[dict],
    characteristics: str | None = None,
    flags: list[dict] | None = None,
    user_comment: str | None = None,
    title_link: str | None = None,
    width: str | float = "100%",
    outline_level: int | None = 1,
) -> "Table":
    """POI-карточка для Stage 3 PDF.

    Отличия от `entity_card`: выдержки рендерятся с тонами (✓/✗/•), есть
    атрибуция автора с similarity-чипом, есть блок «Характеристики», есть
    info-box комментария (выводится ТОЛЬКО если `user_comment` непустой —
    в PDF пустые поля скрываем; для DOCX-эквивалента см. docx_lib.add_poi_card).

    `excerpts`: список dict
      `{tone, author_name, year?, similarity?, url?, text}`
    `flags`: список dict `{kind, label}` — chip'ы без internal-link
      (в PDF навигация через outline, не через chip-link).
    """
    register_fonts()
    accent = CATEGORY_COLORS[category]
    tint = lighten_hex(accent, 0.93)

    flow: list = []

    # — Header: # + название (опц. link к Google Images) + CATEGORY badge —
    title_color = accent
    title_style = ParagraphStyle(
        "poi_title", fontName=FONT_HEADING, fontSize=13, leading=16,
        textColor=HexColor(f"#{title_color}"), alignment=TA_LEFT,
    )
    # Латинское имя в скобках — ТОЛЬКО если оно есть (иначе пустые `()`).
    local_html = (
        f' <font size="10" color="#6b7280">({xml_escape(name_local)})</font>'
        if name_local and name_local.strip() else ""
    )
    title_text = (
        f'<font color="#6b7280">#{num}</font>&nbsp;'
        f'<b>{xml_escape(name_ru)}</b>{local_html}'
    )
    if title_link:
        # Оборачиваем только имя POI, а не весь header
        title_text = (
            f'<font color="#6b7280">#{num}</font>&nbsp;'
            f'<a href="{xml_escape(title_link)}" color="#{title_color}"><b>'
            f'{xml_escape(name_ru)}</b></a>{local_html}'
        )
    title_p = Paragraph(title_text, title_style)

    badge_style = ParagraphStyle(
        "poi_badge", fontName=FONT_BODY_BOLD, fontSize=8, leading=11,
        textColor=HexColor("#ffffff"), alignment=TA_CENTER,
    )
    badge_p = Paragraph(xml_escape(CATEGORY_SHORT[category]), badge_style)
    badge_cell = Table([[badge_p]], colWidths=[78])
    badge_cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(f"#{accent}")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    header_tbl = Table([[title_p, badge_cell]], colWidths=["*", 84])
    header_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow.append(header_tbl)

    # — Counts line —
    counts_style = ParagraphStyle(
        "poi_counts", fontName=FONT_MONO, fontSize=8.5, leading=12,
        textColor=HexColor("#5b6b7e"),
        spaceBefore=3, spaceAfter=6,
    )
    flow.append(Paragraph(xml_escape(counts_line), counts_style))

    # — Separator —
    sep = Table([[" "]], colWidths=["100%"], rowHeights=[1])
    sep.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#d0d6dd")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flow.append(sep)
    flow.append(Spacer(1, 4))

    # — Excerpts —
    excerpt_style = ParagraphStyle(
        "poi_excerpt", fontName=FONT_BODY, fontSize=10, leading=13,
        textColor=HexColor(COLORS["text"]),
        leftIndent=14, firstLineIndent=-12,
        spaceAfter=4,
    )
    tone_glyphs = {"pos": "✓", "neg": "✗", "neu": "•"}
    for ex in excerpts:
        tone = ex.get("tone", "neu")
        glyph = tone_glyphs.get(tone, "·")
        tone_color = TONE_COLORS.get(tone, "6b7280")

        author = xml_escape(ex.get("author_name", "?"))
        url = ex.get("url")
        title = ex.get("report_title")
        author_html = f'<font color="#1a3a5c"><b>{author}</b></font>'
        # «Название отчёта» — кликабельный chip в скобках после имени
        if title and url:
            author_html += (
                f' <font color="#6b7280">(</font>'
                f'<a href="{xml_escape(url)}" color="#1a3a5c">'
                f'«{xml_escape(title)}»</a>'
                f'<font color="#6b7280">)</font>'
            )
        elif url and not title:
            from urllib.parse import urlparse
            try:
                domain = urlparse(url).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                domain = url
            author_html += (
                f' <a href="{xml_escape(url)}" color="#1a3a5c">'
                f'({xml_escape(domain)})</a>'
            )

        meta_parts = []
        if ex.get("year"):
            meta_parts.append(f'<font color="#6b7280">{ex["year"]}</font>')
        sim = ex.get("similarity")
        if sim:
            sim_color = SIMILARITY_COLORS.get(sim, "6b7280")
            meta_parts.append(
                f'<font color="#{sim_color}" face="{FONT_BODY_BOLD}" '
                f'size="8">{sim}</font>'
            )
        meta_html = " · ".join(meta_parts) if meta_parts else ""

        attribution = author_html
        if meta_html:
            attribution += f' <font color="#9aa3ad">·</font> {meta_html}'

        text_safe = xml_escape(ex.get("text", ""))
        html = (
            f'<font color="#{tone_color}"><b>{glyph}</b></font>&nbsp;'
            f'{attribution}: <font color="{COLORS["text"]}">{text_safe}</font>'
        )
        flow.append(Paragraph(html, excerpt_style))

    flow.append(Spacer(1, 4))

    # — Characteristics —
    if characteristics:
        chars_style = ParagraphStyle(
            "poi_chars", fontName=FONT_BODY, fontSize=10, leading=13,
            textColor=HexColor(COLORS["text"]), spaceAfter=4,
        )
        chars_html = (
            f'<font color="#3b4554"><b>Характеристики:</b></font> '
            f'{xml_escape(characteristics)}'
        )
        flow.append(Paragraph(chars_html, chars_style))

    # — Flag chips —
    if flags:
        chips: list = []
        for fl in flags:
            color = FLAG_COLORS.get(fl.get("kind", ""), "5a6c87")
            chip_style = ParagraphStyle(
                f"poi_chip_{len(chips)}",
                fontName=FONT_BODY_BOLD, fontSize=7.5, leading=10,
                textColor=HexColor(f"#{color}"),
            )
            chip_p = Paragraph(xml_escape(fl.get("label", "").upper()), chip_style)
            chip_cell = Table([[chip_p]])
            chip_cell.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1),
                 HexColor(lighten_hex(color, 0.85))),
                ("BOX", (0, 0), (-1, -1), 0.4, HexColor(f"#{color}")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            chips.append(chip_cell)
        chips_row = Table([chips], colWidths=[None] * len(chips))
        chips_row.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        flow.append(Spacer(1, 2))
        flow.append(chips_row)

    # — User comment (только если непустой; в PDF пустые скрываем) —
    if user_comment and user_comment.strip():
        comment_label_style = ParagraphStyle(
            "poi_comment_label", fontName=FONT_BODY_BOLD,
            fontSize=8.5, leading=11,
            textColor=HexColor("#7a5c00"),
        )
        comment_text_style = ParagraphStyle(
            "poi_comment_text", fontName=FONT_BODY,
            fontSize=10, leading=13,
            textColor=HexColor(COLORS["text"]),
        )
        label_p = Paragraph("КОММЕНТАРИЙ ПОЛЬЗОВАТЕЛЯ", comment_label_style)
        text_p = Paragraph(xml_escape(user_comment.strip()), comment_text_style)
        comment_box = Table(
            [[label_p], [text_p]],
            colWidths=["100%"],
        )
        comment_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HexColor("#fef7e0")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, HexColor("#d4a843")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (0, 0), 7),
            ("TOPPADDING", (0, 1), (0, 1), 2),
            ("BOTTOMPADDING", (0, 0), (0, 0), 2),
            ("BOTTOMPADDING", (0, 1), (0, 1), 7),
        ]))
        flow.append(Spacer(1, 6))
        flow.append(comment_box)

    # — Outer wrapper: accent stripe + tinted bg —
    inner = _stack(flow)
    tbl = Table([[inner]], colWidths=[width] if isinstance(width, str) else [width])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(tint)),
        ("LINEBEFORE", (0, 0), (0, -1), 4, HexColor(f"#{accent}")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    # Outline-entry для navigation pane + named destination для links
    slug = f"poi_{num}"
    short_cat = CATEGORY_SHORT[category]
    tbl._dest_slug = slug                                   # type: ignore[attr-defined]
    tbl._outline_title = f"#{num} {name_ru} — {short_cat}"  # type: ignore[attr-defined]
    if outline_level is not None:
        tbl._outline_level = outline_level                  # type: ignore[attr-defined]
    return tbl


def poi_cluster_header(
    *,
    name: str,
    member_count: int,
    note: str,
    width: str | float = "100%",
    outline_level: int | None = 1,
) -> "Table":
    """Заголовок кластера POI (несколько связанных POI выбираются together).

    Синие верх/низ границы, светло-голубой фон. Делает named destination
    `cluster_<slug>` для cross-links.
    """
    register_fonts()
    title_style = ParagraphStyle(
        "cluster_title", fontName=FONT_HEADING, fontSize=12, leading=15,
        textColor=HexColor("#1f3a52"),
    )
    note_style = ParagraphStyle(
        "cluster_note", fontName=FONT_BODY, fontSize=9, leading=12,
        textColor=HexColor("#5b6b7e"),
    )
    label_html = (
        f'<font color="#{FLAG_COLORS["cluster"]}"><b>◆ CLUSTER</b></font>&nbsp; '
        f'{xml_escape(name)} '
        f'<font color="#6b7280" size="10">({member_count} POI)</font>'
    )
    title_p = Paragraph(label_html, title_style)
    note_p = Paragraph(xml_escape(note), note_style)
    box = Table([[title_p], [note_p]], colWidths=[width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#eaf0f8")),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, HexColor(f"#{FLAG_COLORS['cluster']}")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6,
         HexColor(f"#{FLAG_COLORS['cluster']}")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 1), (0, 1), 8),
        ("TOPPADDING", (0, 1), (0, 1), 2),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
    ]))
    # Slug для cluster — для будущих cross-links от member-POI
    import re as _re
    slug = "cluster_" + _re.sub(r"\s+", "_",
                                _re.sub(r"[^\w\s-]", "", name.lower()).strip())
    box._dest_slug = slug                              # type: ignore[attr-defined]
    box._outline_title = f"◆ {name} (cluster, {member_count} POI)"  # type: ignore
    if outline_level is not None:
        box._outline_level = outline_level             # type: ignore[attr-defined]
    return box


def hero_cover_block(
    title: str,
    subtitle: str | None = None,
    *,
    accent_color: str | None = None,
    height_ratio: float = 0.35,
) -> "Table":
    """Full-bleed hero-блок для cover page презентационных PDF.

    Тёмная плашка во всю ширину страницы (`accent_color`, по умолчанию
    `COLORS["primary"]`) с крупным белым заголовком и опц. подзаголовком.
    Высота — `height_ratio` от полезной высоты Frame'а (по умолчанию ~35%).

    Зачем: даёт сильный визуальный «удар» на обложке, отличающий PDF от
    отчёта-в-документе. Используется на Stage 0 (Регионы), может применяться
    на Stage 4/5/1 для унификации презентационного стиля.
    """
    register_fonts()
    bg = accent_color or COLORS["primary"]
    title_style = ParagraphStyle(
        "hero_title",
        fontName=FONT_HEADING,
        fontSize=LAYOUT["size_cover_title"],
        leading=LAYOUT["size_cover_title"] * LAYOUT["line_height_heading"],
        textColor=HexColor(COLORS["bar_text"]),
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    sub_style = ParagraphStyle(
        "hero_sub",
        fontName=FONT_BODY, fontSize=14, leading=20,
        textColor=HexColor(COLORS["bar_text_dim"]),
        alignment=TA_LEFT,
    )
    cell_flow: list = [Paragraph(md_inline_to_rl(title, highlight_todo=False), title_style)]
    if subtitle:
        cell_flow.append(Paragraph(md_inline_to_rl(subtitle, highlight_todo=False), sub_style))
    inner = _stack(cell_flow)
    # min_height — оценка под landscape A4 (~210mm − margins ~ 170mm = 482pt
    # полезной высоты; 35% ≈ 168pt). Для portrait выйдет чуть ниже относительно
    # страницы — это норм, hero не должен забирать половину портрета.
    min_height = 482 * height_ratio
    tbl = Table([[inner]], colWidths=["100%"], rowHeights=[min_height])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 28),
        ("RIGHTPADDING", (0, 0), (-1, -1), 28),
        ("TOPPADDING", (0, 0), (-1, -1), 24),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 24),
    ]))
    return tbl


# ---------------------------------------------------------------------------
# Smoke check
# ---------------------------------------------------------------------------


def smoke_check(output_path: str | Path = "/tmp/pdf_lib_smoke.pdf") -> str:
    """Сгенерировать минимальный PDF — проверка, что вся цепочка работает."""
    register_fonts()
    styles = get_styles()
    doc = make_doc(output_path, title="pdf_lib smoke")
    story = [
        para("Smoke test — Stage 5 PDF engine", styles["cover_title"]),
        spacer(20),
        para("Кириллица **жирная**, *курсив*, `моноширинная`, "
             "[ссылка](https://example.com).", styles["body"]),
        para("Inline TODO: проверить отель — должен быть подсвечен жёлтым.",
             styles["body"]),
        warning_box("**Внимание.** Это warning-блок (красная рамка).", styles),
        info_box("Подсказка / TODO-блок (янтарная рамка).", styles),
        data_table(
            [["Колонка", "Значение"], ["День 1", "Ханой"], ["День 2", "Ха-Лонг"]],
            header=True,
        ),
    ]
    doc.build(story)
    return str(output_path)

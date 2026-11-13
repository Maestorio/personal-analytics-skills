"""html_lib.py — HTML-рендер-слой экспорта (параллельно reportlab `pdf_lib`).

Собирает self-contained print-ready HTML на дизайн-системе Claude Design
(`assets/design-tokens.css` + `assets/design-components.css`, шрифты IBM Plex
из `fonts/`). Открывается в браузере как 1:1-превью; конвертируется в PDF
серверным headless-chromium (`--print-to-pdf`) или core `pdf` skill.

Слой извлечения контента (`stages/stageN.extract_content`) переиспользуется
без изменений — html_lib отвечает только за presentation.
"""
from __future__ import annotations

import base64
import html as _html
import json as _json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ASSETS = _HERE / "assets"
_FONTS = _HERE / "fonts"

# (family, style, weight, file) — соответствует var(--font-*) дизайн-токенов.
_FONT_SPECS = [
    ("IBM Plex Sans", "normal", 400, "IBMPlexSans-Regular.ttf"),
    ("IBM Plex Sans", "italic", 400, "IBMPlexSans-Italic.ttf"),
    ("IBM Plex Sans", "normal", 600, "IBMPlexSans-SemiBold.ttf"),
    ("IBM Plex Sans", "normal", 700, "IBMPlexSans-Bold.ttf"),
    ("IBM Plex Mono", "normal", 400, "IBMPlexMono-Regular.ttf"),
    ("IBM Plex Mono", "normal", 600, "IBMPlexMono-SemiBold.ttf"),
]


def _font_faces(*, embed: bool) -> str:
    """@font-face блок: base64-встроенные TTF (self-contained) или ссылки на
    ./fonts (для серверного пайплайна, где шрифты лежат рядом)."""
    out = []
    for family, style, weight, fname in _FONT_SPECS:
        path = _FONTS / fname
        if embed and path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            src = f"url('data:font/ttf;base64,{b64}') format('truetype')"
        else:
            src = f"url('fonts/{fname}') format('truetype')"
        out.append(
            f"@font-face{{font-family:'{family}';font-style:{style};"
            f"font-weight:{weight};font-display:swap;src:{src};}}"
        )
    return "\n".join(out)


def _css() -> str:
    tokens = (_ASSETS / "design-tokens.css").read_text(encoding="utf-8")
    comp = (_ASSETS / "design-components.css").read_text(encoding="utf-8")
    return tokens + "\n" + comp


# Печатная нормализация поверх дизайн-CSS: лист = страница A4, без экранного
# фона/тени; каждая `.page` — на новый лист. Плюс экранные добавки (только
# @media screen — печать/HTML→PDF не затрагиваются): фон-канва из токена и
# мобильная адаптация (лист без фикс-ширины, таблицы со скроллом).
_PRINT_CSS = (
    "html,body{margin:0;background:var(--canvas,#f4f1ea);}"
    ".page{margin:0 auto;}"
    # box-sizing:border-box — БЕЗ media-условия, и на экране, и в печати.
    # `.page` в дизайн-CSS: width:794px (=A4 при 96dpi) + padding:var(--pad)
    # с обеих сторон. При content-box внешняя ширина = 794+2*48 = 890px, то
    # есть на 96px (12%) шире листа A4 — HTML→PDF молча срезал правый край
    # (полосы дат, правые колонки таблиц, край карты). Раньше правило стояло
    # только под @media screen с пометкой «печать — ровно A4»; про padding
    # там забыли. Держать общим: экранное превью и PDF обязаны совпадать 1:1.
    ".page{box-sizing:border-box;}"
    "@media print{"
    "  @page{size:A4;margin:0;}"
    "  html,body{background:#fff !important;}"
    "  .page{box-shadow:none !important;margin:0 !important;}"
    # Карточки не должны разрезаться разрывом страницы:
    # break-inside:avoid держит карточку целиком на одном листе; margin-bottom —
    # чтобы отступ между карточками не терялся, если разрыв всё же встал сразу
    # после карточки (bottom-margin браузеры печати иногда схлопывают у края).
    "  .scard,.poi,.opt-card,.day,.note-item{"
    "break-inside:avoid;page-break-inside:avoid;margin-bottom:var(--s1,9px);}"
    "}"
    # Экран (любая ширина): лист внутренне резиновый — width:min(A4, 100%)
    # вместо фиксированных 794px. Ключ: НЕ зависит от срабатывания брейкпоинта,
    # поэтому мобильная раскладка работает и внутри iframe панели-просмотрщика
    # (iOS Safari внутри iframe часто игнорирует @media max-width и раздувает лист
    # под контент → горизонтальный сдвиг). overflow-x:hidden — жёсткий backstop:
    # влево/вправо не сдвинуть, если контента там нет. Медиа/таблицы не вылезают.
    "@media screen{"
    "  html,body{max-width:100%;overflow-x:hidden;}"
    # width:min(794,100%) вместе с общим box-sizing:border-box (выше) даёт
    # лист, который ужимается по вьюпорту и не вылезает за него.
    "  .page{width:min(794px,100%);}"
    "  .page img,.page svg,.page canvas{max-width:100%;height:auto;}"
    "  .cover-title{overflow-wrap:anywhere;}"
    # Широкие таблицы (покрытие Stage 3, сравнение Stage 4) — скролл ВНУТРИ себя
    # (не завися от брейкпоинта: в iframe iOS @media max-width ненадёжен).
    "  .page table{max-width:100%;display:block;overflow-x:auto;}"
    # Длинная TODO-подсветка (`white-space:nowrap` в базе — для коротких чипов)
    # на узком экране должна переноситься, иначе клипуется правым краем.
    "  .page .todo{white-space:normal;}"
    "}"
    "@media screen and (max-width:840px){"
    "  .page{min-height:0;box-shadow:none;}"
    "  :root{--pad:18px;--fs-cover:30px;--passport-k:96px;}"
    "  html,body{background:var(--paper);}"
    # Карточные сетки (регионы Stage 0, карточки Stage 1/2) — в одну колонку:
    # на телефоне 2–3 колонки нечитаемы. cols-1 уже одноколоночна.
    "  .page .scard-grid,.page .scard-grid.cols-2,.page .scard-grid.cols-3{"
    "grid-template-columns:1fr !important;}"
    "  .page .comp-grid{grid-template-columns:1fr 1fr !important;}"
    # Варианты Stage 4 — в столбик (3 колонки на телефоне нечитаемы).
    "  .page .opt-grid{grid-template-columns:1fr !important;}"
    # Карточка Stage 1 (.kv): узкий лейбл-столбец + широкий столбец значения
    # (было auto 1fr → длинный лейбл раздувал левую колонку, значение жалось).
    "  .page .kv{grid-template-columns:minmax(0,38%) 1fr !important;}"
    # Лента маршрута (Stage 5/6): равные колонки — точки распределяются ровно
    # (иначе ширина остановки = ширине названия, узкие города жмутся, длинные
    # растягивают). Ночи прижаты к низу равновысоких колонок → выровнены в ряд.
    "  .page .ribbon-stop{flex:1 1 0;min-width:0;padding:0 3px;}"
    "  .page .ribbon-name{overflow-wrap:anywhere;font-size:10px;line-height:1.2;}"
    "  .page .ribbon-sub{margin-top:auto;}"
    "}"
    # Узкий телефон: статбенд обложки (4 колонки-числа) переносит на 2 в ряд,
    # чтобы значения (даты/бюджет) не обрезались правым краем.
    "@media screen and (max-width:560px){"
    "  .statband{flex-wrap:wrap;}"
    "  .statband .stat{flex:1 0 45%;border-bottom:1px solid var(--line);}"
    "}"
)

# Тема: синхронизируется с кабинетом по ключу localStorage `hub-theme`
# (same-origin: открытый из кабинета экспорт наследует тёмный режим). Как
# ОТДЕЛЬНЫЙ файл (file:// / скачанный / новый origin, где ключа нет) — тема
# СВЕТЛАЯ по умолчанию: системную тёмную схему НЕ подхватываем (решение
# пользователя 2026-07). Тёмные токены — под @media screen, печать всегда светлая.
_THEME_SCRIPT = (
    "<script>(function(){try{"
    'if(localStorage.getItem("hub-theme")==="dark")'
    'document.documentElement.setAttribute("data-theme","dark");'
    "}catch(e){}})();</script>"
)


def head_assets(*, embed_fonts: bool = True, extra_css: str = "") -> str:
    """Голова дизайн-системы для шаблонных страниц (Stage 2 lookup): theme-скрипт
    синхронизации `hub-theme` + `<style>` c @font-face (вшитый IBM Plex),
    дизайн-токенами, печатной нормализацией и опциональным `extra_css`
    (компонентные стили конкретной страницы поверх токенов).

    Отличие от `build_html_document`: не оборачивает документ целиком —
    только содержимое `<head>`, чтобы страница со своей body-разметкой
    (интерактив на плейсхолдерах) получила ту же палитру/шрифты/тему.
    """
    return (
        f"{_THEME_SCRIPT}\n<style>\n"
        f"{_font_faces(embed=embed_fonts)}\n{_css()}\n{_PRINT_CSS}\n{extra_css}\n"
        "</style>"
    )


def nav_layer() -> str:
    """Навигационный слой TNAV (`assets/nav-layer.{css,js}`): оглавление всегда
    под рукой — плавающая панель на телефоне, липкий рельс на десктопе, шторка
    со списком дней/POI/карточек, «Сегодня» и «Заранее» с сохраняемыми
    отметками подготовки.

    Меню строится СКРИПТОМ из самого документа (плашки разделов, `.day`,
    `.poi`, `.scard`, `.opt-card`) — генератор ничего под меню не размечает,
    поэтому оно не может разойтись с содержимым. Печати не касается:
    `#tnav-root` скрыт в `@media print`, `[ ]` пунктов возвращается на бумагу.
    """
    css = (_ASSETS / "nav-layer.css").read_text(encoding="utf-8")
    js = (_ASSETS / "nav-layer.js").read_text(encoding="utf-8")
    return (f'<style id="tnav-style">\n{css}\n</style>\n'
            f'<script id="tnav-script">\n{js}\n</script>')


def prep_config_block(md_name: str) -> str:
    """`<script type="application/json">` с целью записи отметок подготовки.

    Правила нормализации приезжают в страницу из `prep_sync` — JS строит из них
    RegExp, второй реализации правил нет (контракт «ноль дрейфа», как у
    edit-слоя Stage 3). Нет имени файла — блока нет, и слой честно говорит, что
    отметки живут только в браузере."""
    if not md_name:
        return ""
    try:
        from export import prep_sync
    except ImportError:  # запуск из каталога export/
        import prep_sync  # type: ignore
    cfg = _json.dumps(prep_sync.js_config(md_name), ensure_ascii=False)
    return f'<script type="application/json" id="tnav-prep-config">{cfg}</script>'


_NAV_BLOCK_RE = re.compile(
    r'(?:<script type="application/json" id="tnav-prep-config">.*?</script>)?'
    r'\s*<style id="tnav-style">.*?</style>\s*'
    r'<script id="tnav-script">.*?</script>', re.S)


def strip_nav_layer(html: str) -> str:
    """Убрать навигационный слой из готового документа.

    Нужен двум потребителям: промежуточному рендеру HTML→PDF (интерактив в
    документе, который существует ради печати, — мёртвый вес) и идемпотентному
    впрыску (`inject_nav.py`: вырезать старый блок перед вставкой свежего)."""
    return _NAV_BLOCK_RE.sub("", html)


def build_html_document(body: str, *, title: str = "", embed_fonts: bool = True,
                        landscape: bool = False, nav: bool = True,
                        doc_key: str = "", prep_md: str = "") -> str:
    """Собрать полный HTML-документ: <head> с инлайн-CSS+шрифтами + body.

    `landscape=True` — A4 landscape (Stage 0: coffee-table витрина регионов).
    `nav=False` — без навигационного слоя (тесты/спец-случаи).
    `doc_key` — стабильный ключ документа (trip_id) для хранения отметок
    подготовки: у `5_план` и `6_финал` разные заголовки, а чеклист один и тот
    же, и без общего ключа галочки между ними не переносились бы.
    """
    land = ("\n.page{width:1123px;}\n@media print{@page{size:A4 landscape;}}"
            if landscape else "")
    key_attr = f' data-tnav-key="{esc(doc_key)}"' if doc_key else ""
    return (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title>{_THEME_SCRIPT}\n<style>\n"
        f"{_font_faces(embed=embed_fonts)}\n{_css()}\n{_PRINT_CSS}{land}\n"
        f"</style></head><body{key_attr}>{body}"
        f"{prep_config_block(prep_md)}{nav_layer() if nav else ''}</body></html>"
    )


# ---------------------------------------------------------------------------
# Inline markdown → HTML
# ---------------------------------------------------------------------------

# Внутренние якоря — такие же ссылки, как внешние. Сводная таблица «Регионы
# маршрута» стадии 5 ссылается ими на титлер региона (id="region-N") и на дни
# (id="dayN"), и обе цели в документе есть. Пока destination обязан был
# начинаться с http(s)://, якоря под правило не подходили и печатались сырым
# текстом прямо в таблице: «[Ханой](#region-1)», «[3](#day3)».
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:https?://|#)[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"(?<![\"=>/\w])(https?://[^\s<)]+)")
# «Голый» домен без схемы (srail.or.kr, cbr.ru, kobus.co.kr, letskorail.com):
# (sub.)+TLD[/path]. TLD-вайтлист, чтобы не ловить «8.4», «v1.0», «5_final.md».
_DOMAIN_RE = re.compile(
    r"(?<![\w@/.])((?:[a-z0-9-]+\.)+(?:ru|com|net|org|io|info|kr|by|kz|ua)"
    r"(?:/[^\s<)\"']*)?)", re.I)
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<![\*\w])\*([^*\n]+?)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")
# TODO-подсветка: «TODO…» до конца предложения, но НЕ заходя в теги (`<`),
# чтобы не съесть следующую ссылку/разметку (баг спайка с Booking.com).
# Точка разрешена только перед цифрой (даты/цены «12.09.2026», «5.5»), чтобы
# подсветка не обрывалась внутри даты; конец предложения (`. `) по-прежнему рвёт.
_TODO_RE = re.compile(r"(TODO[:：]?(?:[^.<;\n]|\.(?=\d))*)")


def esc(s: str | None) -> str:
    return _html.escape(s or "", quote=True)


# Русификация видимых англицизмов экспорта (бюджет-статусы, форматы поездки).
# Эти токены приходят как контент исходного плана (YAML/таблицы), но в видимом
# выводе должны быть по-русски. Применяется точечно в рендерерах к тексту перед
# md()/mdb() — НЕ глобально, чтобы не трогать URL/код. Порядок важен (длинные
# и составные токены раньше коротких). Границы — \b по латинской части.
_RU_ANGLICISMS: list[tuple] = [
    (re.compile(r"\bmulti[ _-]region[ _-]tour\b", re.I), "мульти-регион-тур"),
    (re.compile(r"\bmulti[ _-]region\b", re.I), "мульти-регион"),
    (re.compile(r"\bcost[ _-]rank\b", re.I), "ранг стоимости"),
    # `open-jaw` НЕ переводим — устоявшийся авиатермин (перелёт «в один конец
    # туда, из другого города обратно»); русского однословного эквивалента нет.
    (re.compile(r"\bVariant\b"), "Вариант"),
    (re.compile(r"\bover[ _-]budget\b", re.I), "превышение бюджета"),
    (re.compile(r"\bunder[ _-]budget\b", re.I), "ниже бюджета"),
    (re.compile(r"\bon[ _-]target\b", re.I), "в рамках бюджета"),
    (re.compile(r"\bvs\.?\s+target\b", re.I), "к плану"),
    (re.compile(r"\bIn[ _-]trip\b"), "В поездке"),
    (re.compile(r"\bin[ _-]trip\b"), "в поездке"),
    (re.compile(r"\bAll[ _-]in\b"), "Всё включено"),
    (re.compile(r"\ball[ _-]in\b"), "всё включено"),
    (re.compile(r"\bPre[ _-]trip\b"), "До поездки"),
    (re.compile(r"\bpre[ _-]trip\b"), "до поездки"),
    # Регистр сохраняем парой правил (как In-trip/all-in): «Reading list при
    # этом широкий» — начало фразы, ловить его строчной формой нельзя.
    (re.compile(r"\bReading[ _-]list\b"), "Список для чтения"),
    (re.compile(r"\breading[ _-]list\b"), "список для чтения"),
    (re.compile(r"\bscore\b", re.I), "балл"),
    (re.compile(r"\bsimilarity\b", re.I), "похожесть"),
    # Режимы агрегации Stage 3 в прозе warnings (в blockquote тела и YAML
    # остаются EN — машинный якорь `_REGIME_RE` / `aggregation_mode`).
    # Составная форма первой: иначе «scarce-режим» → «скудный-режим» (дефис).
    (re.compile(r"\bscarce[ _-]режим", re.I), "скудный режим"),
    (re.compile(r"\babundant[ _-]режим", re.I), "обильный режим"),
    (re.compile(r"\bscarce\b", re.I), "скудный"),
    (re.compile(r"\babundant\b", re.I), "обильный"),
]


def plate(title: str, *, sub: bool = False) -> str:
    """Плашка секции (дизайн-система). filled — РОВНО ОДНА на стадию (её
    заголовок); группы внутри — `sub=True` (`section-plate section-plate--sub`,
    всегда с базовым классом).

    Моно-индекс `§ SN` убран (по решению пользователя — читался как шум).
    """
    cls = "section-plate section-plate--sub" if sub else "section-plate"
    return f'<div class="{cls}"><span class="sp-title">{esc(title)}</span></div>'


def legend_line(legend_text: str, *,
                prefix: str = "RU = EN из исходных артефактов") -> str:
    """Сноска-легенда соответствия RU↔EN (Р2): видимый вывод русский, .md-артефакт
    остаётся с EN-таксонами. `legend_text` — готовая строка `taxonomy.legend(...)`;
    единый хелпер, чтобы разметка сноски совпадала между стадиями."""
    if not legend_text:
        return ""
    return (f'<p class="muted" style="font-size:var(--fs-small)">'
            f'{esc(prefix)}: {esc(legend_text)}</p>')


def anno(text: str, *, first: bool = False) -> str:
    """Моно-разделитель подсекции/смены темы (дизайн-система `.anno`).
    Первый на странице — `first=True` (без верхнего отступа/бордера)."""
    cls = "anno first" if first else "anno"
    return f'<div class="{cls}">{esc(text)}</div>'


def ru_anglicisms(text: str | None) -> str:
    """Заменить известные англицизмы экспорта на русские эквиваленты.

    Точечный косметический проход для видимого вывода (бюджет-таблицы,
    форматы): `on_target` → «в рамках бюджета», `In-trip` → «В поездке`,
    `all-in` → «всё включено», `multi_region_tour` → «мульти-регион-тур».
    Прочий текст не трогает.
    """
    if not text:
        return text or ""
    for pat, repl in _RU_ANGLICISMS:
        text = pat.sub(repl, text)
    return text


def md_inline(text: str, *, todo: bool = True) -> str:
    """Inline markdown → HTML: ссылки, код, bold/italic, TODO-подсветка.

    Порядок: escape → ссылки (защищаем сентинелами) → код → bold/italic →
    TODO → восстановление ссылок. Так TODO/bold не лезут внутрь href/текста
    ссылок, а `<`-граница в _TODO_RE не даёт подсветке съесть соседний тег.
    """
    if not text:
        return ""
    t = text.replace("\\$", "$")
    t = esc(t)
    # ссылки → сентинелы (чтобы последующие правила их не трогали)
    stash: list[str] = []

    def _stash(tag: str) -> str:
        stash.append(tag)
        return f"\x00L{len(stash) - 1}\x00"

    t = _LINK_RE.sub(lambda m: _stash(
        f'<a class="lnk" href="{m.group(2)}">{m.group(1)}</a>'), t)
    t = _BARE_URL_RE.sub(lambda m: _stash(
        f'<a class="lnk lnk--mono" href="{m.group(1)}">{m.group(1)}</a>'), t)
    # Голые домены → ссылки (https://). После http-URL (чтобы не дублировать),
    # до code/bold (чтобы не лезть внутрь span/тегов).
    t = _DOMAIN_RE.sub(lambda m: _stash(
        f'<a class="lnk lnk--mono" href="https://{m.group(1)}">{m.group(1)}</a>'), t)
    t = _CODE_RE.sub(r'<span class="num">\1</span>', t)
    t = _BOLD_RE.sub(r"<b>\1</b>", t)
    t = _ITALIC_RE.sub(r"<em>\1</em>", t)
    if todo:
        t = _TODO_RE.sub(r'<span class="todo">\1</span>', t)
    # восстановить ссылки
    t = re.sub(r"\x00L(\d+)\x00", lambda m: stash[int(m.group(1))], t)
    return t


_TBL_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+")


def _md_table(lines: list[str]) -> str:
    rows = []
    for ln in lines:
        if _TBL_SEP_RE.match(ln) and set(ln.strip()) <= set("|:- "):
            continue
        rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    if not rows:
        return ""
    head = "".join(f"<th>{md_inline(c, todo=False)}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in r) + "</tr>"
                   for r in rows[1:])
    return (f'<table class="data-table data-table--zebra"><thead><tr>{head}</tr>'
            f"</thead><tbody>{body}</tbody></table>")


def md_block(text: str) -> str:
    """Block-level markdown → HTML: параграфы, md-таблицы (→ .data-table),
    bullet-списки (→ .notelist с ▸). Inline-разметка через md_inline."""
    if not text:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if re.fullmatch(r"\s*[-*_]{3,}\s*", ln):  # markdown horizontal rule
            out.append('<hr style="border:0;border-top:1px solid var(--line);'
                       'margin:var(--s2) 0">')
            i += 1
            continue
        is_table = "|" in ln and (ln.strip().startswith("|")
                                  or (i + 1 < n and _TBL_SEP_RE.match(lines[i + 1])))
        if is_table:
            tbl = []
            while i < n and "|" in lines[i]:
                tbl.append(lines[i]); i += 1
            out.append(_md_table(tbl)); continue
        if _BULLET_RE.match(ln):
            raw_items: list[tuple[int, str]] = []  # (indent, text)
            while i < n and _BULLET_RE.match(lines[i]):
                raw = lines[i]
                indent = len(raw) - len(raw.lstrip(" \t"))
                raw_items.append((indent, _BULLET_RE.sub("", raw)))
                i += 1
            # Уровни вложенности — из уникальных отступов: подпункты сдвигаются
            # вправо (например, стыковки под «Транзит»). Контент — в одном
            # обёрточном <div> (.note-item это grid 1em/1fr; инлайн <b>/<a> иначе
            # блокифицируются в отдельные grid-элементы → текст по слову на строку).
            level = {ind: k for k, ind in enumerate(sorted({ind for ind, _ in raw_items}))}
            lis = "".join(
                f'<div class="note-item"'
                + (f' style="margin-left:{level[ind] * 1.4:.1f}em"' if level[ind] else "")
                + f'><div>{md_inline(t)}</div></div>'
                for ind, t in raw_items
            )
            out.append(f'<div class="notelist">{lis}</div>'); continue
        para = [ln]; i += 1
        while i < n and lines[i].strip() and "|" not in lines[i] and not _BULLET_RE.match(lines[i]):
            para.append(lines[i]); i += 1
        out.append(f"<p>{md_inline(' '.join(para))}</p>")
    return "".join(out)


# ---------------------------------------------------------------------------
# HTML → PDF (серверная конвертация)
# ---------------------------------------------------------------------------

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "google-chrome", "chromium", "chromium-browser", "chrome",
]


def _find_chromium() -> str | None:
    for c in _CHROME_CANDIDATES:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    return None


def _have_weasyprint() -> bool:
    """weasyprint реально пригоден (импортируется без падения).

    При отсутствии нативных либ weasyprint **печатает варнинг в stdout** и падает
    на использовании — поэтому пробный импорт гасим (иначе шум ломает JSON-вывод
    CLI) и считаем движок доступным только если импорт прошёл.
    """
    import importlib.util
    if importlib.util.find_spec("weasyprint") is None:
        return False
    import contextlib
    import io
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            from weasyprint import HTML  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _find_wkhtmltopdf() -> str | None:
    return shutil.which("wkhtmltopdf")


def _wkhtmltopdf_opt_in() -> bool:
    """wkhtmltopdf — только явный опт (env `TRAVEL_PDF_ENGINE=wkhtmltopdf`).

    Qt WebKit ≈2012 не поддерживает CSS grid — паспорт/kv/comp/карточки
    рассыпаются в столбик. Вне авто-цепочки."""
    return os.environ.get("TRAVEL_PDF_ENGINE") == "wkhtmltopdf"


def pdf_engine_available() -> str | None:
    """Имя первого доступного движка HTML→PDF, или None.

    Авто-цепочка: headless-chromium (ближе всего к серверному
    `--print-to-pdf`, поддерживает `oklch()`) → weasyprint (чистый Python,
    типичен в окружении core `pdf` skill). wkhtmltopdf исключён из авто-цепочки
    (деградация качества — без CSS grid) и включается только явным опт-ином
    `TRAVEL_PDF_ENGINE=wkhtmltopdf`.
    """
    if _find_chromium():
        return "chromium"
    if _have_weasyprint():
        return "weasyprint"
    if _wkhtmltopdf_opt_in() and _find_wkhtmltopdf():
        return "wkhtmltopdf"
    return None


def _run_chromium(chromium: str, html_str: str, output_path: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(html_str, encoding="utf-8")
        subprocess.run(
            [chromium, "--headless=new", "--disable-gpu", "--no-sandbox",
             f"--print-to-pdf={output_path}", "--no-pdf-header-footer",
             src.as_uri()],
            check=True, capture_output=True, timeout=180,
        )


def _run_weasyprint(html_str: str, output_path: str) -> None:
    from weasyprint import HTML  # type: ignore
    HTML(string=html_str).write_pdf(output_path)


_LANDSCAPE_CSS_RE = re.compile(r"@page\s*\{[^}]*\blandscape\b", re.I)


def _run_wkhtmltopdf(wk: str, html_str: str, output_path: str) -> None:
    """wkhtmltopdf не читает CSS `@page{size:… landscape}` — при landscape-CSS
    в документе добавляем CLI-флаг `--orientation Landscape` (иначе печатает
    портретом, обрезая landscape-раскладку)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(html_str, encoding="utf-8")
        cmd = [wk, "--enable-local-file-access", "--quiet"]
        if _LANDSCAPE_CSS_RE.search(html_str):
            cmd += ["--orientation", "Landscape"]
        cmd += [str(src), output_path]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)


def html_to_pdf(html_str: str, output_path: str | Path) -> str:
    """Конвертировать HTML-строку в PDF первым РАБОТАЮЩИМ движком. Возвращает путь.

    Авто-цепочка: chromium (`--print-to-pdf`) → weasyprint. wkhtmltopdf в
    авто-цепочку не входит (Qt WebKit ≈2012 без CSS grid — карточки/паспорт
    рассыпаются) и подключается только явным опт-ином
    `TRAVEL_PDF_ENGINE=wkhtmltopdf`. Движок пропускается не только если
    отсутствует, но и если **упал** (сбой ведёт к следующему кандидату, а не
    к общему провалу) — так конвертация переживает сломанный локальный
    chromium/нативные либы weasyprint. Если ни один не сработал —
    RuntimeError со stderr каждого упавшего движка (вызывающий код отдаёт
    HTML core `pdf` skill или возвращает HTML-экспорт).
    """
    output_path = str(output_path)
    errors: list[str] = []
    engines: list[tuple[str, object]] = []
    chromium = _find_chromium()
    if chromium:
        engines.append(("chromium", lambda: _run_chromium(chromium, html_str, output_path)))
    if _have_weasyprint():
        engines.append(("weasyprint", lambda: _run_weasyprint(html_str, output_path)))
    if _wkhtmltopdf_opt_in():
        wk = _find_wkhtmltopdf()
        if wk:
            engines.append(("wkhtmltopdf", lambda: _run_wkhtmltopdf(wk, html_str, output_path)))

    for name, run in engines:
        try:
            run()  # type: ignore[operator]
            return output_path
        except Exception as e:  # noqa: BLE001 — падение движка ⇒ следующий кандидат
            detail = e
            if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                stderr = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else str(e.stderr)
                detail = stderr.strip()[-300:]
            errors.append(f"{name}: {detail}")

    tail = ("; упавшие движки — " + " | ".join(errors)) if errors else ""
    raise RuntimeError(
        "нет РАБОТАЮЩЕГО движка HTML→PDF в авто-цепочке (chromium / weasyprint). "
        "На платформе Claude.ai конвертацию выполняет core `pdf` skill (handoff — "
        "штатный путь); локально поставь chromium или `pip install weasyprint`. "
        "wkhtmltopdf (Qt WebKit ≈2012, без поддержки CSS grid — карточки/паспорт "
        "рассыпаются) можно включить в обход авто-цепочки явным "
        "TRAVEL_PDF_ENGINE=wkhtmltopdf — это деградация качества, не рекомендуется."
        + tail
    )

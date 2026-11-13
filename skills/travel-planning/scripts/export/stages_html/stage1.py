"""Stage 1 → HTML (база DR-отчётов, дизайн-система Claude Design).

Переиспользует `stages.stage1.extract_content` и его позиционные хелперы
(поля карточки живут по номерам 1..20, лейблы DR-прогонов варьируются —
матчить по label нельзя). Presentation на CSS Design: .scard-grid/.scard для
карточек источников (титул «N · Автор — «Название»» + focus/critical .sig +
платформа + .kv по каноническим полям + ссылка на отчёт), META-диагностика
отдельной секцией (покрытие по регионам, распределения, caveat'ы, источники).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage1 as s1
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage1 as s1  # type: ignore

try:  # SSOT ярлыков (report_tonality / report_focus) — scripts/taxonomy.py
    import taxonomy as tx
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import taxonomy as tx  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
plate = html_lib.plate

# Контракт полноты: ключи extract_content, учтённые build_html. Новый ключ без
# учёта → красный drift-тест.
CONSUMED_KEYS = frozenset({
    "title", "frontmatter", "trip_params", "regions", "cards", "meta",
    "warnings", "total_cards", "critical_count", "sample_curation_note",
})

# Поля, не выводимые kv-строкой: 1–4 ушли в титул/подзаголовок/ссылку карточки;
# {6,8,10,16,17} — политика подавления reportlab-ветки (_FIELDS_DROP, Р7).
_HEADER_FIELDS = {1, 2, 3, 4}
_KV_DROP = _HEADER_FIELDS | s1._FIELDS_DROP


def _card_title(card) -> str:
    """Титул карточки: `N · Автор — «Название»` (позиционные поля 3 и 1).

    Лейблы DR варьируются между прогонами («Имя или ник автора» vs «Автор») —
    поэтому берём поля по номеру, а не по совпадению label, иначе все карточки
    остаются без автора/названия (живой баг Китай stage 1).
    """
    author = s1._extract_author(s1._fv(card.fields, 3))
    _, title = s1._extract_url_and_title(s1._fv(card.fields, 1))
    if author and title:
        return f'{card.num} · {esc(author)} — «{esc(title)}»'
    if author:
        return f'{card.num} · {esc(author)}'
    if title:
        return f'{card.num} · «{esc(title)}»'
    return f'Карточка {card.num}'


def _card_sub(card) -> str:
    """Подзаголовок: платформа/язык · дата публикации · когда поездка (поля 2/4/5)."""
    parts = []
    for num in (2, 4, 5):
        v = s1._fv(card.fields, num)
        if v and not s1._is_empty_value(v):
            parts.append(s1._strip_md_bold(v).strip())
    return " · ".join(parts)


def _badges(card) -> str:
    """Бейджи карточки: тональность/фокус + side-флаги (фото/резидент/iconic)."""
    out = []
    if getattr(card, "is_critical", False):
        out.append(f'<span class="sig sig--red">{esc(tx.label("report_tonality", "critical"))}</span>')
    elif getattr(card, "focus_tag", None):
        out.append(f'<span class="sig sig--weak">{esc(tx.label("report_focus", card.focus_tag))}</span>')
    flags = getattr(card, "flags", None) or set()
    if "photo" in flags:
        out.append(f'<span class="sig sig--weak">{esc(tx.label("flag_badge", "photo"))}</span>')
    if "residence" in flags:
        out.append(f'<span class="sig sig--low">{esc(tx.label("flag_badge", "residence"))}</span>')
    if "iconic" in flags:
        out.append(f'<span class="sig sig--gem">{esc(tx.label("flag_badge", "iconic"))}</span>')
    return "".join(out)


def _scard(card) -> str:
    kv = "".join(
        f"<dt>{esc(s1._FIELD_NAMES.get(num, str(num)))}</dt>"
        f"<dd>{md(s1._ru_field_value(num, s1._strip_md_bold(val)))}</dd>"
        for num in sorted(card.fields)
        if num not in _KV_DROP
        and (val := s1._fv(card.fields, num))
        and not s1._is_empty_value(val)
    )
    url, _ = s1._extract_url_and_title(s1._fv(card.fields, 1))
    link = (f'<a class="lnk lnk--mono" href="{esc(url)}">{esc(url)}</a>' if url else "")
    sub = _card_sub(card)
    sub_html = f'<div class="scard-sub">{esc(sub)}</div>' if sub else ""
    return (
        f'<div class="scard"><div class="scard-head">'
        f'<span class="scard-title">{_card_title(card)}</span>{_badges(card)}</div>'
        f'{sub_html}<dl class="kv">{kv}</dl>{link}</div>'
    )


# ── META-диагностика ────────────────────────────────────────────────────────

def _data_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{esc(str(c))}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{md(str(c))}</td>" for c in r) + "</tr>"
                   for r in rows[1:])
    return ('<table class="data-table data-table--compact data-table--zebra">'
            f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def _passport(rows: list[tuple[str, str]]) -> str:
    return ('<div class="passport">' + "".join(
        f'<div class="passport-row"><div class="passport-k">{esc(k)}</div>'
        f'<div class="passport-v">{md(str(v), todo=False)}</div></div>'
        for k, v in rows if v) + "</div>")


def _notelist(items) -> str:
    lis = "".join(f'<div class="note-item"><div>{md(str(x))}</div></div>' for x in items)
    return f'<div class="notelist">{lis}</div>'


def _meta_section(extracted: dict) -> str:
    meta = extracted.get("meta") or {}
    out: list[str] = []

    # Покрытие по регионам (Регион | Отчётов | POI-критика | critical).
    if extracted.get("regions"):
        rows = s1._coverage_table_rows(extracted)
        if rows and len(rows) > 1:
            out.append(plate("Покрытие по регионам", sub=True))
            out.append(_data_table(rows))

    # Распределения — англ. термины локализуем (backpacker → бэкпэкер).
    dist = meta.get("distributions") or {}
    if dist:
        out.append(plate("Распределения", sub=True))
        for name, items in dist.items():
            localized = [s1._ru_style(it) for it in items]
            out.append(f'<p class="muted"><b>По {esc(str(name))}:</b></p>')
            out.append(_notelist(localized))

    # Сезонные caveat'ы — длинная цитата.
    caveat = meta.get("season_caveat")
    if caveat:
        out.append(plate("Сезонные caveat'ы", sub=True))
        out.append('<div class="box box--info"><span class="box-mark"></span>'
                   f'<div>{mdb(str(caveat))}</div></div>')

    # Источники вне seed-списка.
    outside = meta.get("sources_outside_seed")
    if outside:
        out.append(plate("Источники вне seed-списка", sub=True))
        out.append(_notelist(outside))

    # Источники, проверенные при сборе.
    tried = meta.get("sources_tried")
    if tried:
        out.append(plate("Источники, проверенные при сборе", sub=True))
        out.append(_notelist(tried))

    # Предупреждения — служебные merge-пометки не для читателя.
    warnings = [w for w in (extracted.get("warnings") or [])
                if "sample_curation_note" not in str(w)
                and "merge_dr_additions" not in str(w)]
    cleaned = [c for c in (s1._clean_warning_text(str(w)) for w in warnings) if c]
    if cleaned:
        out.append('<div class="box box--warn"><span class="box-mark"></span>'
                   f'<div>{_notelist(cleaned)}</div></div>')

    return "".join(out)


def build_html(extracted: dict, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True,
               landscape: bool = False) -> str:
    # Ориентация зависит от формата (передаётся из диспетчера):
    #   HTML  → портрет + 1 колонка (для экранного просмотра);
    #   PDF   → landscape + 2 колонки (крупным карточкам источников хватает ширины).
    cards = extracted.get("cards") or []

    parts = ['<div class="page"><div class="guide">']
    parts.append('<div class="cover-kicker">Deep Research · база отчётов</div>')
    # Реальный титул/подзаголовок из YAML/маркера — как в reportlab-обложке
    # (Р9: polish-заголовок эфемерен, _cover_title сам умеет fallback на
    # YAML при его отсутствии).
    parts.append(f'<h1 class="cover-title">{esc(s1._cover_title(extracted))}</h1>')
    sub = s1._cover_subtitle(extracted)
    if sub:
        parts.append(f'<p class="cover-sub">{esc(sub)}</p>')

    # Паспорт поездки (Кто едет / Регионы / Сезон / Темп / …).
    passport_rows = s1._cover_key_params(extracted)
    if passport_rows:
        parts.append(_passport(passport_rows))

    # Mode B: расширение выборки awd.ru (sample_curation_note) — инфо-бокс.
    scn = s1._strip_pipeline_script_ref(str(extracted.get("sample_curation_note") or ""))
    if scn:
        parts.append('<div class="box box--info"><span class="box-mark"></span>'
                     f'<div><b>Расширение выборки:</b> {md(scn)}</div></div>')

    # P0-1: единственная filled-плашка стадии.
    parts.append(plate("База отчётов"))
    # landscape (PDF) → 2 колонки; портрет (HTML) → 1 колонка на всю ширину
    # (иначе детальные карточки «едут»).
    grid_cls = "scard-grid" if landscape else "scard-grid cols-1"
    parts.append(f'<div class="{grid_cls}">' + "".join(_scard(c) for c in cards) + "</div>")

    meta_html = _meta_section(extracted)
    if meta_html:
        parts.append(plate("META-диагностика", sub=True))
        parts.append(meta_html)

    parts.append("</div></div>")
    doc = html_lib.build_html_document(
        "".join(parts), title="Источники Deep Research",
        embed_fonts=embed_fonts, landscape=landscape)
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc

"""Stage 2 → HTML (similarity-витрина, дизайн-система Claude Design).

`stages.stage2.extract_content` → Stage2Content. Presentation на CSS Design:
.scard (автор + .score-big + категория .sig + .comps со score-метрами +
.proscons), сводная .data-table по всем авторам.
"""
from __future__ import annotations

from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage2 as s2, stage5 as s5
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage2 as s2, stage5 as s5  # type: ignore

md = html_lib.md_inline
esc = html_lib.esc
mk_plate = html_lib.plate
ru = html_lib.ru_anglicisms  # русификация видимых англицизмов прозы (Р7, как в RL)
tx = s2.taxonomy  # SSOT ярлыков (author_category / similarity_component)

# CSS-класс бейджа по ключу категории; ярлык — через taxonomy (author_category).
_CAT_SIG = {"HIGH": "strong", "OUTLIER": "gem", "MEDIUM": "weak",
            "LOW": "red", "UNSCORED": "low"}


def _sig(cat: str) -> str:
    # Пустая категория → `"".split()` = [] (IndexError на [0]); guard как в stage0.
    parts = (cat or "").upper().split()
    key = parts[0] if parts else ""
    cls = _CAT_SIG.get(key, "weak")
    rulabel = tx.label("author_category", cat) if cat else ""
    return f'<span class="sig sig--{cls}">{esc(rulabel)}</span>'


def _comps(components) -> str:
    out = []
    for c in components or []:
        w = max(0, min(100, round((getattr(c, "value", 0) or 0) * 10)))
        # Короткая RU-форма лейбла метра (independence → «самост.»), Р2.
        label = tx.short_label("similarity_component", (c.name or ""))
        out.append(
            f'<div class="comp"><span class="comp-k">{esc(label)}</span>'
            f'<span class="meter-track"><span class="meter-fill" style="width:{w}%"></span></span>'
            f'<span class="comp-v">{esc(_fmt(c.value))}</span></div>'
        )
    return f'<div class="comps">{"".join(out)}</div>' if out else ""


def _proscons(a) -> str:
    rows = []
    if getattr(a, "pull_up", None):
        rows.append(f'<div class="pc up">{md(a.pull_up)}</div>')
    if getattr(a, "pull_down", None):
        rows.append(f'<div class="pc down">{md(a.pull_down)}</div>')
    return f'<div class="proscons">{"".join(rows)}</div>' if rows else ""


def _fmt(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v) == int(v) else f"{v}"


def _author_card(a, anchor: str | None = None) -> str:
    sub_bits: list[str] = []
    if getattr(a, "signal", None):
        sub_bits.append(a.signal)
    if getattr(a, "user_added", False):
        sub_bits.append("добавлен вручную")
    if getattr(a, "low_confidence", None):
        sub_bits.append(f"оценено {a.low_confidence[0]}/{a.low_confidence[1]} критериев")
    sub = " · ".join(sub_bits)
    link = (f'<a class="lnk lnk--mono" href="{esc(a.url)}">{esc(a.url)}</a>'
            if getattr(a, "url", None) else "")
    aid = f' id="{esc(anchor)}"' if anchor else ""
    return (
        f'<div class="scard"{aid}><div class="scard-head">'
        f'<span class="scard-title">{esc(a.name)}</span>'
        f'<span class="score-big">{esc(_fmt(a.score))}</span>{_sig(a.category)}</div>'
        f'{f"<div class=\"scard-sub\">{esc(sub)}</div>" if sub else ""}'
        f'{_comps(a.components)}{_proscons(a)}{link}</div>'
    )


def _cohort(title: str, authors: list, anchors: dict | None = None) -> str:
    if not authors:
        return ""
    # P0-1: когорта — sub-плашка (не filled); cols-1 — карточки автора
    # детализированы (score-метры, «тянет вверх/вниз»), в 2 колонки не помещаются.
    cards = "".join(
        _author_card(a, (anchors or {}).get(id(a))) for a in authors)
    return (mk_plate(f"{title} · {len(authors)}", sub=True)
            + f'<div class="scard-grid cols-1">{cards}</div>')


def build_html(extracted, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True) -> str:
    ex = extracted
    country = s5._human_cover_title({"trip_id": getattr(ex, "trip_id", "")})

    parts = ['<div class="page"><div class="guide">']
    parts.append('<div class="cover-kicker">Similarity filter · Deep Research</div>')
    parts.append(f'<h1 class="cover-title">{esc(country)}</h1>')
    if getattr(ex, "confidence_line", None):
        parts.append(f'<p class="cover-sub">Похожесть авторов на профиль поездки. {esc(ru(ex.confidence_line))}</p>')

    if getattr(ex, "context", ""):
        parts.append('<div class="box box--info"><span class="box-mark"></span>'
                     f'<div>{md(ru(ex.context))}</div></div>')

    # распределение по категориям (ведущий EN-таксон → RU, Р2). Числовые
    # колонки «Авторов»/«Доля» — по центру (левый край смотрится криво).
    if getattr(ex, "distribution", None):
        dist_rows = [[s2._localize_dist_category(c), cnt, share]
                     for c, cnt, share in ex.distribution]
        rows = [["Категория", "Авторов", "Доля"]] + dist_rows
        head = "".join(
            f'<th{" style=\"text-align:center\"" if i else ""}>{esc(c)}</th>'
            for i, c in enumerate(rows[0]))
        body = "".join(
            "<tr>" + "".join(
                f'<td{" style=\"text-align:center\"" if i else ""}>{esc(str(c))}</td>'
                for i, c in enumerate(r))
            + "</tr>"
            for r in rows[1:])
        parts.append(f'<table class="data-table data-table--compact data-table--zebra">'
                     f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')

    # предупреждения / примечания по severity (эталон reportlab-ветки)
    warns, infos = s2._split_warnings_by_severity(getattr(ex, "warnings", None) or [])
    if warns:
        parts.append(mk_plate("Предупреждения", sub=True))
        items = "".join(f'<div class="note-item"><div>{md(ru(str(w)))}</div></div>' for w in warns)
        parts.append('<div class="box box--warn"><span class="box-mark"></span>'
                     f'<div><div class="notelist">{items}</div></div></div>')
    if infos:
        parts.append(mk_plate("Примечания", sub=True))
        items = "".join(f'<div class="note-item"><div>{md(ru(str(i)))}</div></div>' for i in infos)
        parts.append('<div class="box box--info"><span class="box-mark"></span>'
                     f'<div><div class="notelist">{items}</div></div></div>')

    # Якоря карточек: каждому автору с карточкой — стабильный id, чтобы из
    # сводной таблицы «Все авторы» вести ссылку на его карточку.
    carded = []
    for lst in (getattr(ex, "high", None), getattr(ex, "outlier", None),
                getattr(ex, "extended", None)):
        carded.extend(lst or [])
    anchors_by_objid: dict[int, str] = {}
    anchor_by_name: dict[str, str] = {}
    for i, a in enumerate(carded):
        aid = f"author-{i}"
        anchors_by_objid[id(a)] = aid
        anchor_by_name.setdefault(a.name, aid)  # первое вхождение имени

    # P0-1: единственная filled-плашка стадии; когорты внутри — sub.
    parts.append(mk_plate("Похожесть авторов"))
    parts.append(_cohort("HIGH — наиболее похожие", getattr(ex, "high", None), anchors_by_objid))
    parts.append(_cohort("OUTLIER — низкий total, но сильный сигнал", getattr(ex, "outlier", None), anchors_by_objid))
    parts.append(_cohort("Расширенное чтение", getattr(ex, "extended", None), anchors_by_objid))
    parts.append(_cohort("Без оценки, но с сигналом", getattr(ex, "unscored_with_signal", None), anchors_by_objid))
    parts.append(_cohort("Оценка по авторам (MEDIUM / LOW)", getattr(ex, "compact", None), anchors_by_objid))

    # сводная по всем
    full = getattr(ex, "full_table", None) or []
    if full:
        parts.append(mk_plate("Все авторы", sub=True))
        head = ("<th>Автор</th><th class=\"num\">Score</th><th>Категория</th>"
                "<th>Ссылка</th>")

        def _name_cell(a) -> str:
            anc = anchor_by_name.get(a.name)
            return (f'<a class="lnk" href="#{anc}">{esc(a.name)}</a>' if anc
                    else esc(a.name))

        def _link_cell(a) -> str:
            return (f'<a class="lnk lnk--mono" href="{esc(a.url)}">↗</a>'
                    if getattr(a, "url", None) else "")
        body = "".join(
            f'<tr><td>{_name_cell(a)}</td><td class="num">{esc(_fmt(a.score))}</td>'
            f"<td>{esc(tx.label('author_category', a.category) if a.category else '')}</td>"
            f"<td>{_link_cell(a)}</td></tr>"
            for a in full)
        parts.append(f'<table class="data-table data-table--compact data-table--zebra">'
                     f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')

    # Легенда RU=EN (Р2): видимый вывод русский, .md остаётся с EN-таксонами.
    parts.append(html_lib.legend_line(tx.legend("author_category"),
                                      prefix="Категории сходства (RU = EN)"))

    parts.append("</div></div>")
    doc = html_lib.build_html_document(
        "".join(parts), title=f"{country} — похожие авторы", embed_fonts=embed_fonts)
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc

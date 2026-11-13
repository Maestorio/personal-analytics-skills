"""Stage 6 → HTML (дизайн-система Claude Design).

Stage 6 = устаканенный 5_vX план + обзорная **географическая** карта (границы
страны + рёбра-полудуги, matplotlib → PNG, base64) + приложения (дорожное
досье / бронирования / углубления). Переиспускает рендер Stage 5 (stages_html.
stage5) на 5_vX и добавляет карту после обложки + приложения в конец.
"""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage5 as s5x, stage6 as s6x
    from export.stages_html import stage5 as h5
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage5 as s5x, stage6 as s6x  # type: ignore
    from stages_html import stage5 as h5  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
ru = html_lib.ru_anglicisms  # единый русификатор англицизмов (all-in, cost rank…)


def _route_spec(s5_ex: dict, s6: dict):
    """Построить route-spec карты (из координат 6_final или гео:-маркеров 5_vX)."""
    title = s6x._map_title(s5_ex, s6)
    rg = s5x.group_regions(s5_ex.get("days") or [])
    spec = None
    if s6.get("coords_section"):
        spec = s6x.build_route_spec(s6["coords_section"], title=title, region_groups=rg)
    if not spec:
        spec = s6x.extract_route_spec(s5_ex.get("days") or [], title=title)
    return spec


def _bases(spec) -> list | None:
    """База-последовательность маршрута (без аэропорта) для ленты + локатора:
    [{name, nums:set}] в порядке прохождения, дни из координатных меток узлов."""
    if not spec:
        return None
    spec = s6x._strip_airport_route(spec)
    seen: list[int] = []
    out: list[dict] = []
    for i in spec["route"]:
        if i in seen:
            continue
        seen.append(i)
        n = spec["nodes"][i]
        out.append({"name": n[2], "nums": h5.parse_day_nums(str(n[3]))})
    return out or None


def _map_png_b64(spec) -> str | None:
    """Отрисовать обзорную карту (matplotlib) → base64 PNG, или None."""
    if not s6x.MATPLOTLIB_AVAILABLE or not spec:
        return None
    countries = s6x.load_countries()
    if not countries:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            png = s6x.render_route_map(spec, countries, os.path.join(tmp, "map"))
        except Exception:
            return None
        if not png or not os.path.exists(png):
            return None
        return base64.b64encode(Path(png).read_bytes()).decode("ascii")


def _map_figure(b64: str) -> str:
    return (
        '<figure class="routemap" style="width:auto;margin:var(--s3) auto;text-align:center">'
        f'<img src="data:image/png;base64,{b64}" '
        'style="max-width:80%;height:auto;display:block;margin:0 auto" alt="Карта маршрута">'
        "</figure>"
    )


def _appendix(title: str, groups: list[dict]) -> str:
    if not groups:
        return ""
    # P0-1: приложение — sub-плашка (единственная filled — «Маршрут по дням»);
    # его под-секции — моно-разделители .anno.
    out = [html_lib.plate(title, sub=True)]
    for g in groups:
        t = (g.get("title") or "").strip()
        if t and t.lower() != title.lower():
            out.append(html_lib.anno(ru(t)))
        out.append(mdb(ru(g.get("body", ""))))
    return "".join(out)


def build_html(s6_parsed: dict, output_path: str | Path, *,
               source_file: str | Path | None = None,
               recipient: str = "self", embed_fonts: bool = True) -> str:
    """Собрать Stage 6 HTML. `s6_parsed` — распарсенный 6_final.md; 5_vX
    резолвится из YAML `source_plan` (или `source_file`)."""
    s5_parsed = s6x._load_source_plan(s6_parsed, source_file)
    if not s5_parsed:
        # Просьба, а не констатация: сообщение называет искомый файл, место
        # поиска и что там лежит вместо него — иначе человек гадает, чего от
        # него хотят (см. s6x.source_plan_request).
        raise RuntimeError(s6x.source_plan_request(s6_parsed))
    s5_ex = s5x.extract_content(s5_parsed, input_path=[source_file, output_path])
    s6 = s6x.extract_content(s6_parsed)

    spec = _route_spec(s5_ex, s6)
    bases = _bases(spec)
    # Текстовые фильтры дорожного документа — один раз, до обложки и тела:
    # обе части читают один и тот же `s5_ex`.
    # `s6` фильтруем ПОСЛЕ построения spec: координаты карты разбирались из
    # сырого текста, и трогать их фильтром незачем.
    s5_ex = s5x.apply_trip_text_filters(s5_ex, s5x.TRIP_DROP_HTML)
    s6 = s5x.apply_trip_text_filters(s6, s5x.TRIP_DROP_HTML)
    parts = [f'<div class="page"><div class="guide">'
             f'{h5._cover(s5_ex, bases=bases, drop=s5x.TRIP_DROP_HTML)}']

    # Провенанс: из какого 5_vX собран финал (иначе не понять, не устарел ли
    # он относительно более свежего плана).
    src_plan = (s6.get("cover") or {}).get("source_plan")
    if src_plan:
        parts.append('<p class="muted" style="font-size:var(--fs-small)">'
                     f'Собран из плана: {html_lib.esc(str(src_plan))}</p>')

    # Обзорная карта — сразу после обложки (как в reportlab-ассемблере).
    b64 = _map_png_b64(spec)
    if b64:
        parts.append(html_lib.plate("Обзорная карта маршрута", sub=True))
        parts.append(_map_figure(b64))
        parts.append('<p class="muted" style="font-size:var(--fs-small)">'
                     'Пины — порядок остановок; красным выделены узкие звенья '
                     'переездов, пунктиром — перелёты. Координаты — ориентир, '
                     'не для навигации.</p>')

    # Полное тело плана 5_vX (Шапка / критические пункты / дни с titler-блоками /
    # сводные таблицы / план рисков / TODO / чеклист) — общий рендер с Stage 5,
    # паритет с reportlab (где Stage 6 прогоняет полный stage5.build_pdf).
    # Stage 6 — дорожный документ (телефон в поездке). Планировочная кухня
    # 5_vX сюда не едет, но TODO и чеклист ОСТАЮТСЯ: страница интерактивна,
    # отметки пишутся обратно в 5_vX, и по ним видно, что уже сделано.
    parts.extend(h5.body_sections(s5_ex, recipient=recipient, bases=bases,
                                  drop=s5x.TRIP_DROP_HTML))

    # Приложения Stage 6.
    parts.append(_appendix("Дорожное досье", s6.get("dossier") or []))
    # Бронирования: интро-тело + H3-подсекции (тело не терять при наличии H3).
    if s6.get("bookings") and s6["bookings"].strip():
        parts.append(html_lib.plate("Бронирования", sub=True))
        parts.append(mdb(ru(s6["bookings"])))
        for sub in s6.get("bookings_subsections") or []:
            t = (sub.get("title") or "").strip()
            if t and t.lower() != "бронирования":
                parts.append(html_lib.anno(ru(t)))
            parts.append(mdb(ru(sub.get("body", ""))))
    parts.append(_appendix("Углубления", s6.get("enrichment") or []))

    parts.append("</div></div>")
    title = f'{s5x._human_cover_title(s5_ex["cover"])} — финальный план с картой'
    # doc_key = trip_id 5_vX: отметки подготовки общие у «плана» и «финала» —
    # чеклист там один и тот же, а <title> разные. Пишутся они В ТОТ ЖЕ 5_vX
    # (у 6_final своего чеклиста нет), поэтому цель ищем с подсказкой source_plan.
    body = "".join(parts)
    doc = html_lib.build_html_document(
        body, title=title, embed_fonts=embed_fonts,
        doc_key=str((s5_ex.get("cover") or {}).get("trip_id") or ""),
        prep_md=h5.prep_target(body, output_path, hint=str(src_plan or ""),
                               source_file=source_file))
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc

"""Stage 0 → HTML (витрина регионов, дизайн-система Claude Design).

Переиспользует `stages.stage0.extract_content` и его хелперы (паспорт, чистка
YAML-жаргона). Presentation на CSS Design: .scard-grid/.scard (карточки
регионов: title + density .sig + описание + «Что увидишь» bullets + foot),
группировка по role (Ядро/Поддержка/Нишевые/Пограничные), .passport,
.box--info (non-canonical со статусом + interest_match). Портрет A4.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage0 as s0, stage5 as s5
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage0 as s0, stage5 as s5  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
ru = html_lib.ru_anglicisms  # русификация видимых англицизмов (multi-region…)
plate = html_lib.plate       # плашки секций (filled / sub)

# Контракт полноты: ключи extract_content, учтённые build_html (потреблены или
# сознательно проигнорированы). Новый ключ без учёта → красный drift-тест.
CONSUMED_KEYS = frozenset({
    "title", "frontmatter", "trip_params", "longlist", "excluded",
    "non_canonical", "context", "tempo", "honest", "warnings",
    "validation_errors",
})

tx = s0.taxonomy  # SSOT ярлыков (region_role_group / content_density)

_ROLE_ORDER = ["core", "supporting", "niche", "borderline"]
# CSS-класс бейджа плотности по ключу; ярлык — через taxonomy (content_density).
_DENSITY_CLS = {"HIGH": "strong", "MED": "weak", "MEDIUM": "weak", "LOW": "low"}


def _passport(rows: list[tuple[str, str]]) -> str:
    return ('<div class="passport">' + "".join(
        f'<div class="passport-row"><div class="passport-k">{esc(k)}</div>'
        f'<div class="passport-v">{md(str(v), todo=False)}</div></div>'
        for k, v in rows if v) + "</div>")


def _density(d: str | None) -> str:
    # Нет плотности — не рисуем бейдж вовсе (не «—»), чтобы карточка без данных
    # не выглядела пустой категорией.
    key = (d or "").strip().upper().split()[0] if (d or "").strip() else ""
    if not key:
        return ""
    cls = _DENSITY_CLS.get(key, "low")
    return f'<span class="sig sig--{cls}">{esc(tx.label("content_density", key))}</span>'


def _bullets(items) -> str:
    """«Что увидишь» — все точки списком .notelist (не только первая)."""
    clean = [re.sub(r"^\s*[-*]\s+", "", b or "") for b in (items or []) if (b or "").strip()]
    if not clean:
        return ""
    lis = "".join(f'<div class="note-item"><div>{md(ru(b), todo=False)}</div></div>'
                  for b in clean)
    return f'<div class="notelist">{lis}</div>'


def _scard(r) -> str:
    # role в подвал не выводим — карточка и так под плашкой своей роли.
    foot: list[str] = []
    nm, no = r.nights_min, r.nights_optimum
    if nm or no:
        rng = f"{nm}–{no}" if (nm and no and nm != no) else f"{nm or no}"
        foot.append(f'<span class="nights">ночи <b>{esc(rng)}</b></span>')
    if getattr(r, "reserve_for", None):
        foot.append(f'<span>резерв → {esc(r.reserve_for)}</span>')
    if getattr(r, "is_non_canonical", False):
        foot.append('<span>вне путеводителей</span>')
    if r.season_note:
        foot.append(f'<span>{esc(r.season_note[:46])}</span>')
    note_html = (f'<div class="scard-note">{md(ru(r.description), todo=False)}</div>'
                 if (r.description or "").strip() else "")
    bullets_html = _bullets(r.description_bullets)
    foot_html = f'<div class="scard-foot">{"".join(foot)}</div>' if foot else ""
    return (
        f'<div class="scard"><div class="scard-head">'
        f'<span class="scard-title">{esc(r.name)}</span>{_density(r.density)}</div>'
        f'{note_html}{bullets_html}{foot_html}</div>'
    )


def _role_groups(longlist: list) -> str:
    by_role: dict[str, list] = {}
    for r in longlist:
        by_role.setdefault((r.role or "").lower(), []).append(r)
    out = []
    ordered = [x for x in _ROLE_ORDER if x in by_role] + \
              [x for x in by_role if x not in _ROLE_ORDER]
    for role in ordered:
        regs = by_role[role]
        # P0-1/P0-4: группы ролей — sub-плашка (ярлык через taxonomy), не filled.
        role_label = tx.label("region_role_group", role) if role else "прочее"
        out.append(plate(f'{role_label} · {len(regs)}', sub=True))
        out.append('<div class="scard-grid cols-3">'
                   + "".join(_scard(r) for r in regs) + "</div>")
    return "".join(out)


def _excluded_card(e) -> str:
    """Кандидат на замену: имя + «не вошло: причина» + описание + «Что увидишь».
    Пустой note не рендерим — только имя (guard как у non_canonical)."""
    body: list[str] = []
    if (e.reason or "").strip():
        body.append(f'<div class="scard-sub">не вошло: {md(ru(e.reason), todo=False)}</div>')
    if (getattr(e, "description", "") or "").strip():
        body.append(f'<div class="scard-note">{md(ru(e.description), todo=False)}</div>')
    body.append(_bullets(getattr(e, "description_bullets", None)))
    return (f'<div class="scard"><div class="scard-head">'
            f'<span class="scard-title">{esc(e.name)}</span></div>'
            f'{"".join(body)}</div>')


def build_html(extracted: dict, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True) -> str:
    fm = extracted.get("frontmatter") or {}
    country = s5._human_cover_title({"trip_id": fm.get("trip_id", "")})

    parts = ['<div class="page"><div class="guide">']
    parts.append('<div class="cover-kicker">Региональная витрина · Deep Research</div>')
    parts.append(f'<h1 class="cover-title">{esc(country)}</h1>')

    # Паспорт поездки — из единого хелпера reportlab (группа/страны/сезон/
    # длительность/темп/регионов в выборке/кандидатов/цель по ночам).
    rows = [(k, v) for k, v in s0._cover_key_params(extracted) if v]
    parts.append(_passport(rows))

    if extracted.get("context"):
        parts.append(plate("Контекст", sub=True))
        parts.append(f'<div class="lead">{mdb(ru(s0._prose(extracted["context"])))}</div>')

    if extracted.get("tempo"):
        parts.append(plate("Темп и распределение", sub=True))
        parts.append(f'<div class="lead">{mdb(ru(s0._prose(extracted["tempo"])))}</div>')

    # P0-1: единственная filled-плашка стадии — заголовок самого лонг-листа;
    # группы ролей внутри (_role_groups) — sub.
    parts.append(plate("Региональный лонг-лист"))
    parts.append(_role_groups(extracted.get("longlist") or []))

    if extracted.get("excluded"):
        parts.append(plate("Регионы вне выборки (кандидаты на замену)", sub=True))
        parts.append('<div class="scard-grid cols-3">'
                     + "".join(_excluded_card(e) for e in extracted["excluded"])
                     + "</div>")

    if extracted.get("non_canonical"):
        # P0-1: sub-плашка (выделена 2px teal сверху, но не filled-стена).
        parts.append(plate("Найдено вне выборки", sub=True))
        for nc in extracted["non_canonical"]:
            status_text = "в выборке" if nc.status == "in_longlist" else "вне выборки"
            tail = md(ru((nc.interest_match or "").strip()), todo=False)
            reason = (nc.reason or "").strip()
            if reason:
                tail = (tail + " — " if tail else "") + md(ru(reason), todo=False)
            body = f'<b>{esc(nc.name)}</b> ({esc(status_text)})'
            body += f'. {tail}' if tail else ""
            parts.append('<div class="box box--info"><span class="box-mark"></span>'
                         f'<div>{body}</div></div>')

    if extracted.get("honest"):
        parts.append(plate("Честная оценка", sub=True))
        parts.append(f'<div class="lead">{mdb(ru(s0._prose(extracted["honest"])))}</div>')

    if extracted.get("warnings"):
        parts.append(plate("Предупреждения", sub=True))
        items = "".join(f'<div class="note-item"><div>{md(str(w))}</div></div>'
                        for w in extracted["warnings"])
        parts.append('<div class="box box--warn"><span class="box-mark"></span>'
                     f'<div><div class="notelist">{items}</div></div></div>')

    parts.append("</div></div>")
    # Портрет A4 (как остальные стадии); 3-колоночный грид .cols-3 рассчитан
    # на 794px (эталон Stage 2).
    doc = html_lib.build_html_document(
        "".join(parts), title=f"{country} — регионы для DR",
        embed_fonts=embed_fonts)
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc

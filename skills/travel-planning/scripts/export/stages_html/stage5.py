"""Stage 5 → HTML (дизайн-система Claude Design).

Переиспользует слой извлечения `stages.stage5.extract_content` без изменений;
здесь — только presentation: контент → разметка на CSS-классах Design
(.cover-*, .statband, .ribbon, .section-plate, .day, .program, .box--*,
.chip--*, .data-table). Конвертация в PDF — `html_lib.html_to_pdf`.
"""
from __future__ import annotations

import re
from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage5 as s5
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage5 as s5  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
ru = html_lib.ru_anglicisms  # русификация видимых англицизмов (on_target, all-in…)

# Контракт полноты: ключи extract_content, учтённые build_html/body_sections.
# Новый ключ без учёта → красный drift-тест.
CONSUMED_KEYS = frozenset({
    "title", "frontmatter", "frontmatter_warnings", "cover", "context",
    "header", "critical_prep", "route_intro", "days", "summary",
    "risk_plan_blocks", "checklist_2w", "todo", "extra",
})


# ── bases / locator ─────────────────────────────────────────────────────────
# `bases` = [{name, nums:set}] в порядке маршрута (из координат Stage 6).

def parse_day_nums(label: str) -> set:
    """«дни 1-2, 16-18» → {1,2,16,17,18}; «дни 3-5» → {3,4,5}."""
    nums: set[int] = set()
    for m in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)|(\d+)", label or ""):
        if m.group(1):
            nums.update(range(int(m.group(1)), int(m.group(2)) + 1))
        elif m.group(3):
            nums.add(int(m.group(3)))
    return nums


_TRIP_YM_RE = re.compile(r"(20\d{2})[-_](\d{2})")


def iso_from_daydates(pairs, year: int) -> dict:
    """[(day_num, 'DD.MM')] + год старта → {day_num: 'ГГГГ-ММ-ДД'}.

    Общий для двух путей: сборки из `.md` (`iso_dates`) и впрыска слоя в уже
    готовый HTML (`inject_nav.py`, где даты читаются из разметки). Год едет на
    +1 при переходе через январь (28.12 → 03.01).
    """
    out: dict[int, str] = {}
    prev_month = None
    for num, raw in pairs:
        if not num or not raw:
            continue
        day_s, mon_s = str(raw).split(".")
        month = int(mon_s)
        if prev_month is not None and month < prev_month:
            year += 1
        prev_month = month
        out[int(num)] = f"{year:04d}-{month:02d}-{int(day_s):02d}"
    return out


def iso_dates(extracted: dict) -> dict:
    """{day_num: 'ГГГГ-ММ-ДД'} — календарные даты дней плана.

    В заголовке дня дата стоит без года («День 5 (12.04 Пн)»), поэтому год
    берётся из `trip_id` (`регион_b_2027-04`) или из frontmatter
    `season`/`start_date`. Внутри поездки год переносится при переходе через
    январь (28.12 → 03.01). Года нет — возвращаем пусто: навигационный слой
    тогда просто не показывает кнопку «Сегодня» (штатное состояние).
    """
    cover = extracted.get("cover") or {}
    fm = extracted.get("frontmatter") or {}
    probe = " ".join(str(x) for x in (cover.get("trip_id"), fm.get("trip_id"),
                                      fm.get("season"), fm.get("start_date")) if x)
    m = _TRIP_YM_RE.search(probe)
    if not m:
        return {}
    pairs = [(getattr(d, "day_num", None), s5._day_date(d))   # «DD.MM» или пусто
             for d in extracted.get("days") or []]
    return iso_from_daydates(pairs, int(m.group(1)))


def _locator(day_num, bases) -> str:
    """Локатор «вы здесь» справа от заголовка дня (дизайн-язык .locator):
    бейдж базы + имя + ряд точек с активной (.is-now)."""
    if not bases or not day_num:
        return ""
    cur = next((i for i, b in enumerate(bases) if day_num in b["nums"]), None)
    if cur is None:
        return ""
    dots = "".join(f'<span class="loc-dot{" is-now" if j == cur else ""}"></span>'
                   for j in range(len(bases)))
    return (f'<span class="locator"><span class="loc-badge">{cur + 1}</span>'
            f'<span class="loc-here">{esc(bases[cur]["name"])}</span>{dots}</span>')


# ── cover ──────────────────────────────────────────────────────────────────

def _cover(extracted: dict, bases: list | None = None,
           drop: tuple[str, ...] = ()) -> str:
    """Обложка плана. `drop` — набор дорожного документа (см.
    `stages/stage5.TRIP_DROP_*`): «variant» снимает «Вариант X» из кикера,
    «budget_note» — подстрочник с вердиктом о попадании в бюджет."""
    cover = extracted["cover"]
    days = extracted["days"]
    groups = s5.group_regions(days)
    n_bases = len(bases) if bases else len(groups)

    variant = s5._variant_letter(cover) if "variant" not in drop else ""
    kicker = " · ".join(
        ["Финальный план"]
        + ([f"Вариант {variant}"] if variant else [])
        + (["Ретроспектива"] if cover.get("retrospective") else [])
    )
    title = s5._human_cover_title(cover)
    thesis = s5._extract_thesis(extracted.get("context") or "") or ""

    daydates = [d for d in (s5._day_date(x) for x in days) if d]
    stats: list[tuple[str, str, str]] = []
    if cover.get("duration_nights"):
        stats.append(("Длительность", str(cover["duration_nights"]), "ночей"))
    if daydates:
        stats.append(("Даты", f'{daydates[0]}<span class="u"> – </span>{daydates[-1]}', ""))
    if n_bases:
        stats.append(("Базы", str(n_bases), "городов"))
    if cover.get("budget_target_rub"):
        stats.append(("Бюджет всё включено", f"₽{round(cover['budget_target_rub'] / 1000)}", "K"))
    statband = "".join(
        f'<div class="stat"><div class="stat-k">{esc(k)}</div>'
        f'<div class="stat-v">{v}{f" <span class=\"u\">{esc(u)}</span>" if u else ""}</div></div>'
        for k, v, u in stats
    )

    ribbon_src = ([(b["name"], f'{len(b["nums"])} н') for b in bases] if bases
                  else [(g.name, f"{len(g.days)} н") for g in groups])
    ribbon = ""
    if ribbon_src:
        # is-end — только домашняя база (старт); маршрут-петля возвращается в неё,
        # поэтому последнюю базу как «конец» не маркируем.
        stops = "".join(
            f'<div class="ribbon-stop{" is-end" if i == 0 else ""}">'
            f'<span class="ribbon-dot"></span>'
            f'<span class="ribbon-name">{esc(nm)}</span>'
            f'<span class="ribbon-sub">{esc(sub)}</span></div>'
            for i, (nm, sub) in enumerate(ribbon_src)
        )
        ribbon = f'<div class="ribbon">{stops}</div>'

    note = (s5._cover_budget_note(cover) or "") if "budget_note" not in drop else ""
    note_html = (f'<p class="muted" style="margin-top:6px;font-size:var(--fs-small)">'
                 f'{md(ru(note), todo=False)}</p>' if note else "")
    return (
        f'<div class="cover-kicker">{esc(kicker)}</div>'
        f'<h1 class="cover-title">{esc(title)}</h1>'
        f'<p class="cover-sub">{md(ru(thesis), todo=False)}</p>'
        f'{ribbon}'
        f'<div class="statband">{statband}</div>'
        f'{note_html}'
    )


# ── day ────────────────────────────────────────────────────────────────────

_SRC_RE = re.compile(r"\*?\s*(Источник:[^*\n]*?)\s*\*?\s*$")


def _blank(s: str | None) -> bool:
    """Пустой маркер: пусто или только тире/точки/пробелы (`⚠️ —`, `💰 —`)."""
    return not (s or "").strip().strip("—–-. ").strip()


def _program(content: str) -> str:
    intro, bullets = s5.split_bullets_and_intro(content)
    intro = (intro or "").strip()
    # Голая метка «**Программа:**» — не рендерим отдельным параграфом; реальный
    # intro-текст (или маркер вовсе без bullets) — рендерим (иначе теряется).
    if s5._BOLD_LABEL_RE.match(intro):
        intro = ""
    items = []
    for b in bullets:
        b = b.strip()
        src = ""
        m = _SRC_RE.search(b)
        if m:
            src = f'<em class="prog-src">{md(m.group(1), todo=False)}</em>'
            b = b[: m.start()].rstrip(" .—–-")
        items.append(
            '<div class="prog-item"><span class="prog-mark"></span>'
            f'<div>{md(b)}{src}</div></div>'
        )
    intro_html = f"<p>{md(intro)}</p>" if intro else ""
    program_html = f'<div class="program">{"".join(items)}</div>' if items else ""
    return intro_html + program_html


def _day(d, *, recipient: str, bases: list | None = None,
         dates: dict | None = None) -> str:
    bar, subtitle = s5._split_day_heading(d.heading)
    transfer = ("переезд" in (d.heading or "").lower()) or any(
        m.icon == "📍" and "→" in (m.content or "") for m in d.markers
    )
    # Только погода — чип брони рисуется в блоке отеля (.hotel), чтобы не
    # дублировался в новых локациях (день со сменой отеля).
    chips = "".join(
        f'<span class="chip chip--weather"><span class="chip-dot"></span>{esc(lbl)}</span> '
        for lbl, _fg, _bg in s5._day_status_chips(d) if lbl.startswith("погода")
    )
    budget = None
    hotel_rendered = False
    blocks: list[str] = []
    if d.intro:
        blocks.append(f"<p>{md(d.intro)}</p>")
    for m in d.markers:
        if m.icon == "💰":
            b = m.content.strip()
            budget = b if not _blank(b) else None
        elif m.icon in ("⚠️", "⚠"):
            if recipient == "parents":
                continue
            wc = m.content.strip()
            if _blank(wc):  # пустой warn-маркер (`⚠️ —`) — не рисуем пустой бокс
                continue
            blocks.append(
                '<div class="box box--warn"><span class="box-mark"></span>'
                f"<div>{md(wc)}</div></div>"
            )
        elif m.icon == "🏨":
            hotel_rendered = True
            book = f'<span class="chip chip--book"><span class="chip-dot"></span>бронь: {esc(d.booking)}</span> ' if d.booking else ""
            hname, hrest = _hotel_split(m.content)
            name_html = f'<span class="hotel-name">{esc(hname)}</span>' if hname else ""
            blocks.append(
                f'<div class="hotel"><div>{book}{name_html}</div>'
                f'<div class="hotel-meta">{md(hrest)}</div></div>'
            )
        elif m.icon == "🎯":
            blocks.append(_program(m.content))
        else:  # 📍 локация / переезд
            # P2-1: оранжевым горит только реальный переезд; «Локация» — нейтральная.
            is_tr = "переезд" in (m.label or "").lower() or "→" in (m.content or "")
            tag_cls = "move-tag" if is_tr else "move-tag move-tag--loc"
            blocks.append(
                f'<div class="move"><span class="{tag_cls}">{esc(m.label)}</span>'
                f"<span>{md(m.content.strip())}</span></div>"
            )
    # Fallback-чип брони: день с бронью, но без 🏨-блока (иначе бронь теряется).
    if d.booking and not hotel_rendered:
        chips = (f'<span class="chip chip--book"><span class="chip-dot"></span>'
                 f'бронь: {esc(d.booking)}</span> ') + chips
    foot = (f'<div class="day-foot"><span class="daybudget">Бюджет дня '
            f'<span class="num">{esc(budget)}</span></span></div>' if budget else "")
    title_h = f'<h3 class="day-title">{esc(subtitle)}</h3>' if subtitle else ""
    locator = _locator(getattr(d, "day_num", None), bases)
    chips_row = f'<div style="margin:4px 0 2px">{chips}</div>' if chips else ""
    cls = "day day--transfer" if transfer else "day"
    day_id = f' id="day{d.day_num}"' if getattr(d, "day_num", None) else ""
    # data-date — календарная дата дня для навигационного слоя («Сегодня» /
    # «до старта N дней»). Нет разрешимого года → атрибута нет, слой молчит.
    iso = (dates or {}).get(getattr(d, "day_num", None))
    day_dt = f' data-date="{esc(iso)}"' if iso else ""
    return (
        f'<div class="{cls}"{day_id}{day_dt}><div class="day-head">'
        f'<span class="day-date">{esc(bar)}</span>{title_h}{locator}</div>'
        f"{chips_row}{''.join(blocks)}{foot}</div>"
    )


# ── tables / sections ──────────────────────────────────────────────────────

def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{md(ru(c), todo=False)}</th>" for c in rows[0])
    body = "".join(
        "<tr>" + "".join(f"<td>{md(ru(c))}</td>" for c in r) + "</tr>" for r in rows[1:]
    )
    return (f'<table class="data-table data-table--zebra">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


def _plate(title: str, *, sub: bool = False) -> str:
    return html_lib.plate(title, sub=sub)


def _blocks_html(blocks: list[dict]) -> str:
    """Рендер списка блоков extract_tables_and_text: таблицы (`table`) + проза
    (`text` → md_block). Общий для сводных таблиц и плана рисков."""
    out: list[str] = []
    for blk in blocks or []:
        if blk.get("type") == "table" and blk.get("rows"):
            out.append(_table(blk["rows"]))
        elif blk.get("type") == "text" and (blk.get("content") or "").strip():
            out.append(mdb(ru(blk["content"])))
    return "".join(out)


def _summary_item(item: dict) -> str:
    """Сводная секция: заголовок + блоки. Рендерит И таблицы (`table`), И прозу/
    списки (`text` → md_block). Пустую секцию (без рендерящихся блоков) не выводит —
    чтобы не оставался голый заголовок (баг «пустая ГАСТРОНОМИЯ»)."""
    body = _blocks_html(item.get("blocks", []))
    if not body:
        return ""
    return _plate(item["title"], sub=True) + body


# ── регионы маршрута (сводная таблица + titler-блоки) ───────────────────────

def _region_summary_html(groups: list) -> str:
    """Сводная таблица регионов: Регион | Дни | [Даты] | Ночи | Главное | Бюджет.
    Имя региона и номера дней — ссылки-якоря (#region-N / #dayN)."""
    region_dates = []
    for g in groups:
        dl = [x for x in (s5._day_date(d) for d in g.days) if x]
        region_dates.append(f"{dl[0]}–{dl[-1]}" if len(dl) > 1 else (dl[0] if dl else ""))
    has_dates = any(region_dates)
    header = (["Регион", "Дни"] + (["Даты"] if has_dates else [])
              + ["Ночи", "Главное", "Бюджет"])
    rows = [header]
    for gi, g in enumerate(groups, start=1):
        nums = [d.day_num for d in g.days if d.day_num]
        days_links = "–".join(f"[{n}](#day{n})" for n in nums)
        row = [f"[{g.name}](#region-{gi})", days_links]
        if has_dates:
            row.append(region_dates[gi - 1])
        row += [str(len(g.days)), g.main or "", g.budget or ""]
        rows.append(row)
    return _table(rows)


def _region_titler_html(gi: int, total: int, g) -> str:
    """Titler-блок региона перед его первым днём: РЕГИОН N ИЗ M + мета + поля."""
    dates_list = [x for x in (s5._day_date(d) for d in g.days) if x]
    dates = (f"{dates_list[0]}–{dates_list[-1]}" if len(dates_list) > 1
             else (dates_list[0] if dates_list else ""))
    nums = [d.day_num for d in g.days if d.day_num]
    day_range = (f"дни {nums[0]}–{nums[-1]}" if len(nums) > 1
                 else (f"день {nums[0]}" if nums else ""))
    meta_bits = [b for b in (day_range, dates, f"{len(g.days)} ноч.") if b]
    base = g.fields.get("база")
    if base:
        meta_bits.append(str(base))
    meta = " · ".join(meta_bits)
    intro = g.fields.get("описание")
    intro_html = (f'<p class="muted">{md(ru(intro), todo=False)}</p>'
                  if (intro or "").strip() else "")
    bullets = s5._region_titler_bullets(g.fields)
    bl_html = "".join(f'<div class="note-item"><div><b>{esc(l)}:</b> {md(v)}</div></div>'
                      for l, v in bullets)
    bl_html = f'<div class="notelist">{bl_html}</div>' if bl_html else ""
    return (f'<div class="region-bar" id="region-{gi}"><span class="rname">'
            f'РЕГИОН {gi} ИЗ {total} · {esc(g.name)}</span>'
            f'<span class="rmode">{esc(meta)}</span></div>{intro_html}{bl_html}')


# P1-3: имя отеля — первый `**…**` после `[[бронь]]`; остальное → hotel-meta.
def _hotel_split(content: str) -> tuple[str, str]:
    s = (content or "").strip()
    m = re.match(r"\*\*([^*]+)\*\*\s*", s)
    if m:
        return m.group(1).strip(), s[m.end():].lstrip(" ,—–-")
    return "", s


# ── entry point ────────────────────────────────────────────────────────────

def body_sections(extracted: dict, *, recipient: str = "self",
                  bases: list | None = None,
                  drop: tuple[str, ...] = ()) -> list[str]:
    """Все секции тела плана (после обложки): контекст/«Чего нет» → регионы →
    Шапка → критические пункты → дни (с titler-блоками) → сводные таблицы →
    план рисков → TODO → чеклист → обоснование → незнакомые H2.

    Общая для Stage 5 (standalone) и Stage 6 (5_vX + карта + приложения),
    чтобы обе ветки давали одинаковое тело (паритет с reportlab, где Stage 6
    прогоняет полный `stage5.build_pdf`)."""
    parts: list[str] = []
    days = extracted.get("days") or []
    groups = s5.group_regions(days)
    dates = iso_dates(extracted)

    # «Чего нет в маршруте» / fallback контекста — у фронта.
    ctx_parts = s5._parse_context_parts(extracted.get("context") or "")
    if ctx_parts.get("fallback"):
        rest = s5._strip_thesis_line(ctx_parts["fallback"])  # тезис уже на обложке
        if rest.strip():
            parts.append(_plate("Контекст", sub=True))
            parts.append(f'<div class="lead">{mdb(ru(rest))}</div>')
    # drop: набор ключей секций (s5.TRIP_DROP_HTML / TRIP_DROP_PDF). Отбор
    # запретительный: незнакомое проходит насквозь.
    elif ctx_parts.get("excluded_rows") and "excluded" not in drop:
        parts.append(_plate("Чего нет в маршруте и почему", sub=True))
        parts.append(_table([["Место", "Причина исключения"], *ctx_parts["excluded_rows"]]))

    # «Регионы маршрута» — сводная таблица.
    if groups:
        parts.append(_plate("Регионы маршрута", sub=True))
        parts.append(_region_summary_html(groups))

    # «Шапка».
    if extracted.get("header"):
        parts.append(_plate("Шапка", sub=True))
        parts.append(mdb(extracted["header"]))

    # «Критические подготовительные пункты».
    if extracted.get("critical_prep"):
        parts.append(_plate("Критические подготовительные пункты", sub=True))
        for prep in extracted["critical_prep"]:
            parts.append(html_lib.anno(prep["title"]))
            parts.append(mdb(prep["body"]))

    # «Маршрут по дням» — titler-блок перед первым днём региона.
    if days:
        parts.append(_plate("Маршрут по дням"))
        if extracted.get("route_intro"):
            parts.append(mdb(extracted["route_intro"]))
        titler_at: dict = {}
        for gi, g in enumerate(groups, start=1):
            first = next((d.day_num for d in g.days if d.day_num), None)
            if first is not None:
                titler_at[first] = (gi, len(groups), g)
        for d in days:
            if getattr(d, "day_num", None) in titler_at:
                gi, total, g = titler_at[d.day_num]
                parts.append(_region_titler_html(gi, total, g))
            parts.append(_day(d, recipient=recipient, bases=bases, dates=dates))

    # «Сводные таблицы».
    for item in extracted.get("summary") or []:
        parts.append(_summary_item(item))

    # «План реагирования на риски» (self only).
    if extracted.get("risk_plan_blocks") and recipient == "self":
        parts.append(_plate("План реагирования на риски", sub=True))
        _risks = extracted["risk_plan_blocks"]
        if "risk_probability" in drop:
            _risks = s5.drop_risk_probability(_risks)
        parts.append(_blocks_html(_risks))

    # «TODO для верификации» (self only).
    if extracted.get("todo") and recipient == "self" and "todo" not in drop:
        parts.append(_plate("TODO для верификации", sub=True))
        for grp in extracted["todo"]:
            parts.append(html_lib.anno(grp["title"]))
            parts.append(mdb(grp["body"]))

    # «Чеклист за 2 недели до поездки».
    if extracted.get("checklist_2w") and "checklist_2w" not in drop:
        parts.append(_plate("Чеклист за 2 недели до поездки", sub=True))
        parts.append(mdb(extracted["checklist_2w"]))

    # Приложение «Обоснование ключевых решений» (logic из контекста, self only).
    if ctx_parts.get("logic_blocks") and recipient == "self" and "logic" not in drop:
        parts.append(_plate("Обоснование ключевых решений", sub=True))
        for blk in ctx_parts["logic_blocks"]:
            parts.append(mdb("\n".join(blk)))

    # Незнакомые H2 (эволюция схемы).
    for ex in (s5.drop_extra_for_trip(extracted.get("extra")) if drop
               else (extracted.get("extra") or [])):
        parts.append(_plate(ex["heading"], sub=True))
        parts.append(mdb(ex["body"]))
        for ss in ex.get("subsections", []):
            parts.append(html_lib.anno(ss["heading"]))
            parts.append(mdb(ss["body"]))

    return parts


def prep_target(body_html: str, output_path: str | Path, *,
                hint: str | None = None,
                source_file: str | Path | None = None) -> str:
    """Имя файла плана, куда слой пишет отметки подготовки, или пусто.

    Выбор — ПО СОДЕРЖИМОМУ (`prep_sync.resolve_plan_md`), имя-подсказка
    (`source_plan` Stage 6) только тай-брейк: у Китая объявленный
    `5_final_plan_v1.md` не совпадает с лежащим на диске `5_final _plan_v1.md`.
    Уверенного кандидата нет → пусто, и слой честно скажет, что отметки живут
    только в браузере."""
    try:
        from export import prep_sync
    except ImportError:  # запуск из каталога export/
        import prep_sync  # type: ignore
    # Кандидаты каталогов — как у резолвера «Кто едет»: вывод может уехать в
    # чужую папку (`--output-dir`), исходник — быть эфемерным polished вне trips/.
    seen: list[Path] = []
    for p in (output_path, source_file):
        if not p:
            continue
        d = Path(p).parent
        if d not in seen:
            seen.append(d)
    for d in seen:
        res = prep_sync.resolve_plan_md(d, body_html, hint=hint)
        if res:
            return res["name"]
    return ""


def build_html(extracted: dict, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True,
               source_file: str | Path | None = None) -> str:
    """Собрать Stage 5 HTML и записать в output_path. Возвращает HTML-строку."""
    parts = [f'<div class="page"><div class="guide">{_cover(extracted)}']
    parts.extend(body_sections(extracted, recipient=recipient))
    parts.append("</div></div>")

    title = f'{s5._human_cover_title(extracted["cover"])} — финальный план'
    body = "".join(parts)
    doc = html_lib.build_html_document(
        body, title=title, embed_fonts=embed_fonts,
        doc_key=str((extracted.get("cover") or {}).get("trip_id") or ""),
        prep_md=prep_target(body, output_path, source_file=source_file))
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc

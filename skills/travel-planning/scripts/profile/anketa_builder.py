"""Рендер анкеты в DOCX из ANKETA_SECTIONS + опц. prefill answers."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

try:
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "python-docx не установлен. Поставь: "
        "`pip install python-docx --break-system-packages`"
    ) from e

from .anketa_spec import (
    ANKETA_SECTIONS,
    Question,
    Subheader,
    Section,
)


GREY = RGBColor(0x6B, 0x72, 0x80)
ACCENT = RGBColor(0x1A, 0x3A, 0x5C)
MUTED = RGBColor(0x9C, 0xA3, 0xAF)
FILLED = RGBColor(0x1F, 0x29, 0x37)


def _add_section_header(doc, number: int, title: str, marker: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(20)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(f"{number}. {title}")
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = ACCENT
    if marker:
        r2 = p.add_run(f"   {marker}")
        r2.italic = True
        r2.font.size = Pt(9)
        r2.font.color.rgb = MUTED


def _add_subheader(doc, title: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(11.5)
    run.font.color.rgb = ACCENT


def _add_text_question(doc, q: Question, prefill_text: str = "") -> None:
    pq = doc.add_paragraph()
    pq.paragraph_format.space_before = Pt(8)
    pq.paragraph_format.space_after = Pt(2)
    rq = pq.add_run("Вопрос: ")
    rq.bold = True
    rq2 = pq.add_run(q.text)
    rq2.bold = True

    if q.hint:
        ph = doc.add_paragraph()
        ph.paragraph_format.space_after = Pt(4)
        ph.paragraph_format.left_indent = Cm(0.4)
        rh = ph.add_run(q.hint)
        rh.italic = True
        rh.font.size = Pt(9.5)
        rh.font.color.rgb = GREY

    pa = doc.add_paragraph()
    pa.paragraph_format.space_after = Pt(6)
    pa.paragraph_format.left_indent = Cm(0.4)
    ra = pa.add_run("Ответ: ")
    ra.bold = True
    if prefill_text:
        rans = pa.add_run(prefill_text)
        rans.font.size = Pt(11)
        rans.font.color.rgb = FILLED


def _add_choice_question(
    doc,
    q: Question,
    selected: Optional[list] = None,
    clarifications: Optional[dict] = None,
) -> None:
    selected = selected or []
    clarifications = clarifications or {}
    multi = (q.type == "multi")

    pq = doc.add_paragraph()
    pq.paragraph_format.space_before = Pt(8)
    pq.paragraph_format.space_after = Pt(2)
    rq = pq.add_run("Вопрос: ")
    rq.bold = True
    rq2 = pq.add_run(q.text)
    rq2.bold = True

    if q.hint:
        ph = doc.add_paragraph()
        ph.paragraph_format.space_after = Pt(4)
        ph.paragraph_format.left_indent = Cm(0.4)
        rh = ph.add_run(q.hint)
        rh.italic = True
        rh.font.size = Pt(9.5)
        rh.font.color.rgb = GREY

    if any(desc for _, desc in q.options):
        pl = doc.add_paragraph()
        pl.paragraph_format.left_indent = Cm(0.4)
        pl.paragraph_format.space_before = Pt(2)
        pl.paragraph_format.space_after = Pt(2)
        rl = pl.add_run("Пояснения:")
        rl.italic = True
        rl.font.size = Pt(9.5)
        rl.font.color.rgb = GREY
        for val, desc in q.options:
            if not desc:
                continue
            pe = doc.add_paragraph()
            pe.paragraph_format.left_indent = Cm(0.8)
            pe.paragraph_format.space_after = Pt(0)
            r_val = pe.add_run(f"— {val}: ")
            r_val.italic = True
            r_val.bold = True
            r_val.font.size = Pt(9.5)
            r_val.font.color.rgb = GREY
            r_desc = pe.add_run(desc)
            r_desc.italic = True
            r_desc.font.size = Pt(9.5)
            r_desc.font.color.rgb = GREY

    pc = doc.add_paragraph()
    pc.paragraph_format.left_indent = Cm(0.4)
    pc.paragraph_format.space_before = Pt(6)
    pc.paragraph_format.space_after = Pt(2)
    rc = pc.add_run(
        "Выбери один или несколько (поставь «x» или «v» в скобках):"
        if multi else
        "Выбери один (поставь «x» или «v» в скобках):"
    )
    rc.bold = True
    rc.font.size = Pt(10)

    for val, _desc in q.options:
        po = doc.add_paragraph()
        po.paragraph_format.left_indent = Cm(0.8)
        po.paragraph_format.space_after = Pt(1)
        mark = "[x]" if val in selected else "[ ]"
        r1 = po.add_run(f"{mark}  ")
        r1.font.size = Pt(11)
        r2 = po.add_run(val)
        r2.font.size = Pt(11)
        if val in selected:
            r1.bold = True
            r1.font.color.rgb = FILLED
            r2.bold = True
            r2.font.color.rgb = FILLED
        if val in clarifications and clarifications[val]:
            r3 = po.add_run(f" ({clarifications[val]})")
            r3.font.size = Pt(11)
            r3.font.color.rgb = FILLED


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


def build_docx(
    out_path: str | Path,
    answers: Optional[dict] = None,
    profile_id: Optional[str] = None,
    profile_updated: Optional[str] = None,
) -> Path:
    """Сгенерировать DOCX с анкетой.

    answers       — None (пустой шаблон, CREATE) или dict qid→answer (UPDATE).
    profile_id    — для подписи в шапке («правка профиля «X»»).
    profile_updated — дата `updated:` исходного профиля (для шапки).

    Возвращает Path к сохранённому файлу.
    """
    answers = answers or {}
    doc = Document()

    for sec in doc.sections:
        sec.top_margin = Cm(2.0)
        sec.bottom_margin = Cm(2.0)
        sec.left_margin = Cm(2.2)
        sec.right_margin = Cm(2.2)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # --- Шапка ---
    title = doc.add_paragraph()
    title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    tr = title.add_run("Анкета профиля путешественника")
    tr.bold = True
    tr.font.size = Pt(20)
    tr.font.color.rgb = ACCENT

    sub = doc.add_paragraph()
    sub.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    sub.paragraph_format.space_after = Pt(6)
    if profile_id:
        sr = sub.add_run(f"travel-planning · правка профиля «{profile_id}»")
    else:
        sr = sub.add_run("travel-planning · создание нового профиля")
    sr.italic = True
    sr.font.size = Pt(10)
    sr.font.color.rgb = GREY

    if profile_id and profile_updated:
        note = doc.add_paragraph()
        note.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        note.paragraph_format.space_after = Pt(12)
        nr = note.add_run(f"предзаполнено из текущей версии профиля от {profile_updated}")
        nr.italic = True
        nr.font.size = Pt(9)
        nr.font.color.rgb = MUTED

    intro = doc.add_paragraph()
    if answers:
        intro_text = (
            "В строках «Ответ: …» подставлено текущее значение из профиля. "
            "Правь там, где хочешь изменить — остальное оставь как есть. "
            "Для вопросов с выбором отмеченные варианты помечены «[x]»; "
            "детали-уточнения подставлены в круглых скобках после варианта. "
            "Чтобы сменить выбор — сними «x» со старого, поставь на новом. "
            "После заполнения пришли файл обратно в чат — скилл применит "
            "изменения к профилю."
        )
    else:
        intro_text = (
            "Заполни строки «Ответ: …» свободным текстом. Для вопросов с выбором "
            "поставь «x» (или «v» / «✓») в скобках выбранных вариантов — например "
            "«[x] активный». "
            "Если хочешь уточнить детали по выбранному варианту, допиши их в "
            "круглых скобках после названия — например «[x] разное по поездке "
            "(в Азии премиум, в Европе средний)». Если секция помечена "
            "[ОПЦИОНАЛЬНО] и не подходит группе — оставь её пустой, при импорте "
            "она будет пропущена и не попадёт в финальный профиль."
        )
    ir = intro.add_run(intro_text)
    ir.font.size = Pt(10)
    ir.font.color.rgb = GREY

    markers = doc.add_paragraph()
    me = markers.add_run(
        "Маркеры секций: [ОБЯЗАТЕЛЬНО] — без них Stage 0 не запустится. "
        "[ВАЖНО] — без них стадии работают, но качество планирования падает. "
        "[ОПЦИОНАЛЬНО] — можно пропустить."
    )
    me.italic = True
    me.font.size = Pt(9.5)
    me.font.color.rgb = GREY

    # --- Секции ---
    for idx, section in enumerate(ANKETA_SECTIONS, start=1):
        _add_section_header(doc, idx, section.title, section.marker)
        for item in section.items:
            if isinstance(item, Subheader):
                _add_subheader(doc, item.title)
                continue
            q: Question = item
            a = answers.get(q.id, {})
            if q.type == "text":
                _add_text_question(doc, q, prefill_text=a.get("text", "") if a else "")
            else:
                _add_choice_question(
                    doc,
                    q,
                    selected=a.get("selected", []) if a else [],
                    clarifications=a.get("clarifications", {}) if a else {},
                )

    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path

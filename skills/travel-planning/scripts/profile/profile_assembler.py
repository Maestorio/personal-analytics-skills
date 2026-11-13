"""Собрать profile.md из answers dict.

YAML frontmatter: profile_id, created, updated, группа_архетип, опц.
incomplete_sections. Тело — по секциям ANKETA_SECTIONS с per-section
форматтерами.

Опциональные секции с пустыми ответами пропускаются.
"""
from __future__ import annotations
from datetime import date
from typing import Optional

from .anketa_spec import (
    ANKETA_SECTIONS,
    ARCHETYPE_LEGACY_ALIASES,
    ARCHETYPE_VALUES,
    Question,
)


# ---------------------------------------------------------------------------
# Per-section форматтеры
# ---------------------------------------------------------------------------

def _fmt_text(q: Question, ans: dict) -> str:
    """Свободный текст → bullet."""
    text = ans.get("text", "").strip()
    if not text:
        return ""
    # Если в тексте уже есть `;` как разделитель — превратим в bullet-список
    if ";" in text and len(text) > 80:
        parts = [p.strip() for p in text.split(";") if p.strip()]
        return "\n".join(f"- {p}" for p in parts)
    return f"- {text}"


def _fmt_choice(q: Question, ans: dict) -> str:
    """Choice (single/multi) → буллеты с clarification."""
    sel = ans.get("selected", []) or []
    clar = ans.get("clarifications", {}) or {}
    if not sel:
        return ""
    lines = []
    for v in sel:
        if v in clar and clar[v]:
            lines.append(f"- {v} — {clar[v]}")
        else:
            lines.append(f"- {v}")
    return "\n".join(lines)


# Спец-форматтеры для сборных секций (Стиль / Форма / Гастро / Бюджет / Платежи)


def _fmt_section_стиль(answers: dict) -> str:
    lines = []
    plan = answers.get("стиль.планирование", {})
    if plan.get("selected"):
        sub = "; ".join(plan["selected"])
        clar = plan.get("clarifications", {})
        suffix = ""
        for v in plan["selected"]:
            if v in clar and clar[v]:
                suffix = f" — {clar[v]}"
                break
        lines.append(f"- Подход к планированию: {sub}{suffix}")
    klass = answers.get("стиль.класс", {})
    if klass.get("selected"):
        v = klass["selected"][0]
        c = klass.get("clarifications", {}).get(v, "")
        lines.append(f"- Класс размещения: {v}" + (f" — {c}" if c else ""))
    tr = answers.get("стиль.транспорт", {})
    if tr.get("selected"):
        names = ", ".join(tr["selected"])
        clar = tr.get("clarifications", {})
        extras = _dedup_preserving([c for v, c in clar.items()
                                     if c and v in tr["selected"]])
        suffix = f" ({'; '.join(extras)})" if extras else ""
        lines.append(f"- Транспорт-предпочтения: {names}{suffix}")
    night = answers.get("стиль.ночные", {})
    if night.get("selected"):
        v = night["selected"][0]
        c = night.get("clarifications", {}).get(v, "")
        lines.append(f"- Ночные переезды: {v}" + (f" — {c}" if c else ""))
    return "\n".join(lines)


def _fmt_section_форма(answers: dict) -> str:
    lines = []
    lvl = answers.get("форма.уровень", {})
    if lvl.get("selected"):
        lines.append(f"- Общий уровень: {lvl['selected'][0]}")
    treks = answers.get("форма.треки", {}).get("text", "").strip()
    if treks:
        lines.append(f"- Треки и подъёмы: {treks}")
    limits = answers.get("форма.ограничения", {}).get("text", "").strip()
    if limits:
        lines.append(f"- Индивидуальные ограничения: {limits}")
    return "\n".join(lines)


def _fmt_section_гастро(answers: dict) -> str:
    lines = []
    style = answers.get("гастро.стиль", {})
    if style.get("selected"):
        names = ", ".join(style["selected"])
        clar = style.get("clarifications", {})
        extras = _dedup_preserving([c for v, c in clar.items()
                                     if c and v in style["selected"]])
        suffix = f" ({'; '.join(extras)})" if extras else ""
        lines.append(f"- Стиль: {names}{suffix}")
    drinks = answers.get("гастро.напитки", {}).get("text", "").strip()
    if drinks:
        lines.append(f"- Кофе/алкоголь/особое питание: {drinks}")
    limits = answers.get("гастро.ограничения", {}).get("text", "").strip()
    if limits:
        lines.append(f"- Ограничения: {limits}")
    return "\n".join(lines)


def _fmt_section_бюджет(answers: dict) -> str:
    lines = []
    o = answers.get("бюджет.ориентир", {}).get("text", "").strip()
    if o:
        lines.append(f"- Ориентир: {o}")
    i = answers.get("бюджет.включает", {}).get("text", "").strip()
    if i:
        lines.append(f"- Что включает: {i}")
    e = answers.get("бюджет.переплата", {}).get("text", "").strip()
    if e:
        lines.append(f"- Готовность переплачивать: {e}")
    return "\n".join(lines)


def _fmt_section_платежи(answers: dict) -> str:
    lines = []
    cards = answers.get("платежи.карты", {})
    if cards.get("selected"):
        names = ", ".join(cards["selected"])
        clar = cards.get("clarifications", {})
        extras = _dedup_preserving([c for v, c in clar.items()
                                     if c and v in cards["selected"]])
        suffix = f" ({'; '.join(extras)})" if extras else ""
        lines.append(f"- Карты: {names}{suffix}")
    local = answers.get("платежи.локальные", {})
    if local.get("selected"):
        lines.append(f"- Локальные платежи: {local['selected'][0]}")
    return "\n".join(lines)


def _dedup_preserving(seq):
    """Снять дубликаты, сохранив порядок."""
    seen = set()
    out = []
    for s in seq:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _fmt_section_вождение(answers: dict) -> str:
    lines = []
    g = answers.get("вождение.готовность", {})
    if g.get("selected"):
        names = ", ".join(g["selected"])
        clar = g.get("clarifications", {})
        extras = _dedup_preserving([c for v, c in clar.items()
                                     if c and v in g["selected"]])
        suffix = f" ({'; '.join(extras)})" if extras else ""
        lines.append(f"- {names}{suffix}")
    geo = answers.get("вождение.гео_ограничения", {}).get("text", "").strip()
    if geo:
        lines.append(f"- Географические ограничения: {geo}")
    return "\n".join(lines)


def _fmt_section_состав(answers: dict) -> str:
    lines = []
    p = answers.get("состав.люди_паспорта", {}).get("text", "").strip()
    if p:
        # Если в строке есть ';' и она длинная — bullet'нем
        if ";" in p:
            for part in p.split(";"):
                if part.strip():
                    lines.append(f"- {part.strip()}")
        else:
            lines.append(f"- {p}")
    langs = answers.get("состав.языки", {}).get("text", "").strip()
    if langs:
        lines.append(f"- Языки: {langs}")
    return "\n".join(lines)


def _fmt_section_фото(answers: dict) -> str:
    lines = []
    lvl = answers.get("фото.уровень", {})
    if lvl.get("selected"):
        v = lvl["selected"][0]
        c = lvl.get("clarifications", {}).get(v, "")
        lines.append(f"- Уровень: {v}" + (f" — {c}" if c else ""))
    genres = answers.get("фото.жанры", {}).get("text", "").strip()
    if genres:
        if ";" in genres:
            for part in genres.split(";"):
                if part.strip():
                    lines.append(f"- {part.strip()}")
        else:
            lines.append(f"- {genres}")
    return "\n".join(lines)


# Реестр секций-форматтеров для составных секций
_COMPOSITE_FORMATTERS = {
    "состав": _fmt_section_состав,
    "стиль": _fmt_section_стиль,
    "вождение": _fmt_section_вождение,
    "форма": _fmt_section_форма,
    "гастро": _fmt_section_гастро,
    "фото": _fmt_section_фото,
    "бюджет": _fmt_section_бюджет,
    "платежи": _fmt_section_платежи,
}


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------


def assemble_profile_md(
    answers: dict,
    profile_id: str,
    created: Optional[str] = None,
    updated: Optional[str] = None,
    human_title: Optional[str] = None,
) -> tuple[str, list]:
    """Сгенерировать markdown профиля. Возвращает (markdown, warnings)."""
    warnings = []

    # Архетип
    arch_ans = answers.get("архетип.значение", {})
    archetype = (arch_ans.get("selected") or [None])[0]
    if not archetype:
        warnings.append("отсутствует обязательное поле `группа_архетип` — выбери архетип в секции 16")
        archetype = "самостоятельные"  # fallback, чтобы файл собрался
    else:
        # legacy-имя (напр. независимые_соло_пара) → каноническое
        archetype = ARCHETYPE_LEGACY_ALIASES.get(archetype, archetype)
    if archetype not in ARCHETYPE_VALUES:
        warnings.append(
            f"архетип «{archetype}» не из допустимого набора {ARCHETYPE_VALUES}"
        )

    today = date.today().isoformat()
    fm_lines = [
        "---",
        f"profile_id: {profile_id}",
        f"created: {created or today}",
        f"updated: {updated or today}",
        f"группа_архетип: {archetype}",
    ]

    # incomplete_sections: список [ВАЖНО]-секций без ответов
    incomplete = []
    for sec in ANKETA_SECTIONS:
        if sec.marker != "[ВАЖНО]":
            continue
        if not _section_has_answer(sec, answers):
            incomplete.append(sec.title)
    if incomplete:
        fm_lines.append("incomplete_sections:")
        for name in incomplete:
            fm_lines.append(f"  - {name}")

    fm_lines.append("---")

    title = human_title or f"# Профиль: {profile_id.replace('_', ' и ').capitalize()}"
    body_parts = [title, ""]

    for sec in ANKETA_SECTIONS:
        if sec.id == "архетип":
            continue  # архетип в frontmatter, не в body
        if not _section_has_answer(sec, answers):
            # Опциональные пропускаем; обязательные оставляем пустую секцию с TODO
            if sec.marker == "[ОБЯЗАТЕЛЬНО]":
                body_parts.append(sec.profile_h2)
                body_parts.append("")
                body_parts.append("- TODO: заполнить (обязательная секция)")
                body_parts.append("")
            continue
        body = _render_section(sec, answers)
        if not body.strip():
            continue
        body_parts.append(sec.profile_h2)
        body_parts.append("")
        body_parts.append(body)
        body_parts.append("")

    md = "\n".join(fm_lines) + "\n\n" + "\n".join(body_parts).strip() + "\n"
    return md, warnings


def _section_has_answer(sec, answers: dict) -> bool:
    for q in sec.questions():
        a = answers.get(q.id)
        if not a:
            continue
        if q.type == "text" and a.get("text", "").strip():
            return True
        if q.type in ("single", "multi") and a.get("selected"):
            return True
    return False


def _render_section(sec, answers: dict) -> str:
    fmt = _COMPOSITE_FORMATTERS.get(sec.id)
    if fmt is not None:
        return fmt(answers)
    # Дефолтный путь: единственный вопрос секции → его форматер
    for q in sec.questions():
        a = answers.get(q.id, {})
        if q.type == "text":
            body = _fmt_text(q, a)
        else:
            body = _fmt_choice(q, a)
        if body:
            return body
    return ""

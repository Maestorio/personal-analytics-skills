#!/usr/bin/env python3
"""Отметки подготовки: сопоставление пунктов HTML ↔ строк плана `.md`.

Отметка «сделано» живёт В САМОЙ СТРОКЕ плана (`- [x] Выкупить билеты`), а не в
отдельном хранилище. Это снимает вопрос «как привязать отметку после
пересборки экспорта»: галочка едет вместе со своей строкой — переформулировали,
переставили, удалили пункт, сгенерировали новую версию плана из этой — отметка
ведёт себя ровно как текст, к которому относится. Побочно она попадает и в PDF
(reportlab-ветка рисует `[x]` как ☑).

Здесь — только сопоставление и правка текста. Сеть, кнопки и авторизация — в
`assets/nav-layer.js` (пишет через тот же write-API, что edit-слой Stage 3).
Регулярки нормализации отдаются в страницу как строки (`js_config`), JS строит
из них RegExp — второй реализации правил нет, расхождение ловится тестом.

ВЫБОР ФАЙЛА ПЛАНА — ПО СОДЕРЖИМОМУ, НЕ ПО ИМЕНИ. Имя врёт: у Китая
`6_final.md` объявляет `source_plan: 5_final_plan_v1.md`, а на диске лежит
`5_final _plan_v1.md` (лишний пробел). Имя используется как подсказка при
равном счёте, решает — доля совпавших пунктов (на реальных данных 48/48 у
Китая и 29/29 у Вьетнама против 4/29 у соседних версий).
"""
from __future__ import annotations

import html as _html
import re
import unicodedata
from pathlib import Path

# ── правила нормализации (SSOT: отсюда же уезжают в JS) ──────────────────────
# Пункт в HTML отрисован (ссылки — тегами, сущности раскрыты), в .md — исходной
# разметкой. Нормализация сводит обе формы к общему виду: текст ссылки без URL,
# без разметки и пунктуации, «ё» = «е», регистр и пробелы схлопнуты.
NORM_RULES: list[tuple[str, str]] = [
    (r"\[([^\]]+)\]\([^)]*\)", r"$1"),   # [текст](url) → текст   ($1 — форма JS
    (r"https?://\S+", " "),              # голые URL              — в Python \1)
    (r"[*_`>#]", ""),                    # md-разметка
    (r"[^0-9A-Za-zА-Яа-яЁё\s]", " "),    # пунктуация/эмодзи
    (r"\s+", " "),                       # пробелы
]
# Строка-чекбокс в .md: «- [ ] текст», «* [x] текст», «  - [х] текст» (кир. «х»),
# а также «- [] текст» — пустые скобки без пробела встречаются в рукописных
# правках плана и у части генераций; при записи приводятся к канону «[ ]»/«[x]».
ITEM_RE_SRC = r"^(\s*[-*]\s*)\[([ xXхХ]?)\]\s*(.*)$"
_ITEM_RE = re.compile(ITEM_RE_SRC)
_HTML_ITEM_RE = re.compile(r'<div class="note-item"[^>]*>(.*?)</div>\s*</div>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def normalize_item(text: str) -> str:
    """Свести пункт к виду, одинаковому для HTML и .md."""
    s = unicodedata.normalize("NFC", text or "")
    s = re.sub(NORM_RULES[0][0], r"\1", s)
    for pat, repl in NORM_RULES[1:]:
        s = re.sub(pat, repl, s)
    return s.replace("ё", "е").replace("Ё", "Е").strip().lower()


def md_checklist(md_text: str) -> list[dict]:
    """Строки-чекбоксы плана: [{line, done, text, key}] (line — с единицы)."""
    out: list[dict] = []
    for i, line in enumerate(md_text.splitlines()):
        m = _ITEM_RE.match(line)
        if not m:
            continue
        out.append({"line": i + 1, "done": m.group(2).strip().lower() in ("x", "х"),
                    "text": m.group(3), "key": normalize_item(m.group(3))})
    return out


def html_checklist(html_text: str) -> list[dict]:
    """Пункты подготовки из собранного экспорта: [{text, done, key}]."""
    out: list[dict] = []
    for m in _HTML_ITEM_RE.finditer(html_text):
        raw = _html.unescape(_TAG_RE.sub("", m.group(1))).strip()
        mm = re.match(r"^\[([ xXхХ]?)\]\s*(.*)$", raw, re.S)
        if not mm:
            continue
        out.append({"text": mm.group(2).strip(), "done": mm.group(1).strip().lower() in ("x", "х"),
                    "key": normalize_item(mm.group(2))})
    return out


def resolve_plan_md(directory: Path | str, html_text: str, *,
                    hint: str | None = None, pattern: str = "5_*.md") -> dict | None:
    """Выбрать файл плана, которому принадлежат пункты экспорта.

    Возвращает {path, name, matched, total, runner_up, by_hint} или None, если
    уверенного кандидата нет. Решает доля совпавших пунктов; имя-подсказка
    (`source_plan`) — только тай-брейк. Порог намеренно высокий: лучше не
    предложить запись вовсе, чем записать отметки в чужую версию плана.
    """
    items = html_checklist(html_text)
    if not items:
        return None
    keys = {i["key"] for i in items if i["key"]}
    if not keys:
        return None
    hint_norm = re.sub(r"\s+", "", (hint or "").lower())

    scored = []
    for md in sorted(Path(directory).glob(pattern)):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        md_keys = {c["key"] for c in md_checklist(text) if c["key"]}
        if not md_keys:
            continue
        scored.append((len(keys & md_keys), re.sub(r"\s+", "", md.name.lower()) == hint_norm, md))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best, by_hint, path = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0
    total = len(keys)
    # уверенность: больше половины пунктов и заметный отрыв от второго кандидата
    if best < max(2, total // 2) or (runner and best < runner * 2):
        return None
    return {"path": path, "name": path.name, "matched": best, "total": total,
            "runner_up": runner, "by_hint": by_hint}


def apply_marks(md_text: str, marks: dict) -> tuple[str, list[str]]:
    """Проставить отметки в тексте плана. `marks` — {ключ пункта: bool}.

    Возвращает (новый текст, ключи, которым не нашлось строки). Эталон для
    JS-зеркала в `nav-layer.js`; неоднозначные ключи (одинаковый текст в двух
    строках) пропускаются — молча угадывать нельзя.
    """
    lines = md_text.split("\n")
    seen: dict[str, list[int]] = {}
    for idx, line in enumerate(lines):
        m = _ITEM_RE.match(line)
        if m:
            seen.setdefault(normalize_item(m.group(3)), []).append(idx)
    missed = []
    for key, done in marks.items():
        idxs = seen.get(key)
        if not idxs or len(idxs) > 1:
            missed.append(key)
            continue
        i = idxs[0]
        m = _ITEM_RE.match(lines[i])
        lines[i] = f"{m.group(1)}[{'x' if done else ' '}] {m.group(3)}"
    return "\n".join(lines), missed


def js_config(md_name: str) -> dict:
    """Конфиг для страницы: имя файла плана + правила нормализации в форме JS."""
    return {
        "mdFile": md_name,
        "normRules": [[pat, repl] for pat, repl in NORM_RULES],
        "itemRe": ITEM_RE_SRC,
    }
